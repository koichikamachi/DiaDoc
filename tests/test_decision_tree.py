"""論争から育つ意思決定ツリー（core.decision_tree）。本物の Gemini は呼ばない。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core import decision_tree as dt
from core.graph import DebateSession
from core.interrupt import intervene
from core.runs import latest_run

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def session(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    s = DebateSession(latest_run("C002_sample_crisis"))
    yield s
    s.close()


def _by_id(nodes):
    return {n.id: n for n in nodes}


def test_before_the_debate_only_mission_and_levers():
    nodes = dt.build(None)
    assert [n.kind for n in nodes] == ["root", "lever", "lever", "lever", "lever"]
    assert all(n.status == "未着手" for n in nodes[1:])
    assert dt.build(None, "資金ショートの回避")[0].label == "資金ショートの回避"


def test_tree_grows_with_the_debate(session):
    session.start()
    sizes = []
    while not session.finished:
        session.step()
        sizes.append(len(dt.build(session.state())))
    assert sizes == sorted(sizes) and sizes[-1] > sizes[0]          # 枝は減らない
    nodes = _by_id(dt.build(session.state()))
    assert nodes["root"].detail == [f"第{session.state().round}ラウンド・決着"]
    assert nodes["T"].status == "宣告" and {"O1", "O2", "O3"} <= set(nodes)
    assert [nodes[o].status for o in ("O1", "O2", "O3")] == ["時期内", "時期内", "時期外"]
    rejected = [n for n in nodes.values() if n.kind == "proposal" and n.status == "棄却"]
    assert rejected and rejected[0].parents == ["root"]           # ブリッジのない定性論はレバーにつかない
    multi = [n for n in nodes.values() if n.kind == "proposal" and len(n.parents) > 1]
    assert multi and all(p.startswith("L") for n in multi for p in n.parents)
    assert all(nodes[f"L{i}"].status == "通過あり" for i in range(1, 5))


def test_premise_and_adoption(session):
    session.start()
    session.step()
    intervene(session, "銀行は返済猶予に応じない見込み")
    assert "銀行は返済猶予" in _by_id(dt.build(session.state()))["H"].detail[0]
    while not session.finished:
        session.step()
    session.adopt("（二）看板維持型（返済猶予で時間を買う）", "メインバンクが猶予に応諾")
    nodes = _by_id(dt.build(session.state()))
    assert nodes["O2"].status == "採択" and "理由・条件：メインバンクが猶予に応諾" in nodes["O2"].detail
    assert nodes["O1"].status == nodes["O3"].status == "不採択"
    assert not any("採択：" in d for d in nodes["H"].detail)       # 採択は前提に混ぜない


def test_graph_source(session):
    from ui.components.tree import build_live

    session.start()
    session.run_round()
    src = build_live(dt.build(session.state())).source
    assert "rankdir=LR" in src and "L1" in src and "診断ミッション" in src
