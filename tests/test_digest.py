"""右と左のパネルに出す要約（core.digest）。同じ状態からは必ず同じ要約が出る。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core import digest
from core.graph import DebateSession
from core.interrupt import intervene
from core.runs import latest_run

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def finished(company):
    s = DebateSession(latest_run(company))
    while not s.finished:
        s.step()
    return s


def test_crisis_proposal_statuses(data):
    st = finished("C002_sample_crisis").state()
    ps = digest.proposals(st)
    assert [p.status for p in ps] == ["棄却", "一部のみ間に合う", "一部のみ間に合う"]
    assert "因果ブリッジ" in ps[0].reason
    assert {b.account: b.in_time for b in ps[1].bridges} == {"sales": False, "lab": True}
    assert {b.account: b.in_time for b in ps[2].bridges} == {"sga_officer": True, "land": False, "rm": True}


def test_crisis_bottlenecks(data):
    s = finished("C002_sample_crisis")
    items = digest.bottlenecks(s.state(), s.ctx.base)
    kinds = [b.kind for b in items]
    assert kinds[0] == "資金" and "92,090" in items[0].text
    assert kinds.count("時期") == 2 and "根拠" in kinds and kinds.count("前提") == 3


def test_sample_company_has_no_cash_bottleneck(data):
    s = finished("C001_sample_alpha")
    items = digest.bottlenecks(s.state(), s.ctx.base)
    assert "資金の不足はない" in items[0].text
    assert digest.triage(s.state()) is None


def test_documents_mark_material_added_during_debate(data):
    s = DebateSession(latest_run("C002_sample_crisis"))
    s.run_round()
    intervene(s, "", attach_name="銀行面談メモ", attach_text="猶予に前向き")
    docs = {d.name: d for d in digest.documents(s.run, s.ctx, s.state())}
    assert docs["銀行面談メモ"].added_round == 2 and docs["銀行面談メモ"].citable
    assert docs["決算報告書第62期（架空）"].kind == "財務"
    assert docs["ヒアリングメモ_第62期（架空）"].kind == "定性" and docs["ヒアリングメモ_第62期（架空）"].added_round is None


def test_triage_summary_takes_the_passed_declaration(data):
    t = digest.triage(finished("C002_sample_crisis").state())
    assert t is not None and len(t.options) == 3 and t.round == 4
