"""回次管理（凍結・引き継ぎ・資料投入）のテスト。

同梱のサンプルデータを一時フォルダに複製して使い、本物の data/ は書き換えない。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPANY = "C001_sample_alpha"


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_sample_has_one_open_initial_run(data):
    from core.runs import list_runs

    runs = list_runs(COMPANY)
    assert [r.run_id for r in runs] == ["run_001_initial"]
    assert runs[0].meta.status == "open"


def test_upload_opens_second_run_and_freezes_first(data):
    from core.mock_engine import handle_upload
    from core.runs import FrozenRunError, Run, list_runs

    before = (data / "companies" / COMPANY / "runs/run_001_initial/debate_log.json").read_bytes()
    run, added, opened = handle_upload(COMPANY, "勘定科目内訳明細書_第73期.pdf", b"%PDF-1.4 dummy")

    assert opened and run.run_id == "run_002_followup"
    assert [r.run_id for r in list_runs(COMPANY)] == ["run_001_initial", "run_002_followup"]
    first = Run(COMPANY, "run_001_initial")
    assert first.frozen
    # 第1次の論争ログは一切変わっていない
    assert (first.path / "debate_log.json").read_bytes() == before
    with pytest.raises(FrozenRunError):
        first.write("debate_log.json", [])
    # 投入資料は第2次の inputs に保存され、財務データは第1次から引き継ぐ
    assert (run.path / "inputs" / "勘定科目内訳明細書_第73期.pdf").exists()
    assert run.financials_source().run_id == "run_001_initial"
    # データ請求 R4 が受領（検証待ち）になり、Radar が受領を応答
    r4 = next(r for r in run.read("data_requests.json") if r["id"] == "R4")
    assert r4["status"] == "受領（検証待ち）"
    assert any(m["who"] == "radar" and "受領しました" in m["text"] for m in added)
    # 差分ファイルが作られる
    assert "R4 仮払金・未収入金等の内訳：請求中 → 受領（検証待ち）" in run.read_text("diff_summary.md")


def test_second_upload_goes_into_the_same_open_run(data):
    from core.mock_engine import handle_upload

    handle_upload(COMPANY, "販管費内訳.xlsx", b"x")
    run, _, opened = handle_upload(COMPANY, "販管費内訳.xlsx", b"y")
    assert not opened and run.run_id == "run_002_followup"
    names = sorted(p.name for p in run.inputs())
    assert names == ["販管費内訳.xlsx", "販管費内訳_2.xlsx"]  # 同名でも上書きしない
    assert (run.path / "inputs" / "販管費内訳.xlsx").read_bytes() == b"x"


def test_intervention_is_reviewed_and_recorded(data):
    from core.mock_engine import apply_intervention
    from core.runs import latest_run

    run = latest_run(COMPANY)
    added = apply_intervention(run, "事業売却は創業家の意向で不可")
    assert any(m["who"] == "rebuild" for m in added)
    tree = {n["id"]: n for n in run.read("decision_tree.json")["nodes"]}
    assert tree["C3"]["status"] == "制約により除外"
    assert "事業売却・カーブアウトは不可" in run.read("constraints.json")["constraints"]


def test_unmatched_intervention_goes_through_formal_review(data):
    from core.mock_engine import apply_intervention
    from core.runs import latest_run

    added = apply_intervention(latest_run(COMPANY), "海外比率を30%まで高めるべきだ")
    judge = next(m for m in added if m["who"] == "judge")
    assert "「退け」" in judge["text"]  # 出典がないので形式審査は退け、前提条件として登録


def test_manual_new_run_carries_state_forward(data):
    from core.mock_engine import apply_intervention, start_manual_run
    from core.runs import latest_run

    apply_intervention(latest_run(COMPANY), "雇用は維持する")
    run = start_manual_run(COMPANY)
    assert run.meta.seq == 2
    assert "人員削減は行わない（雇用維持）" in run.read("constraints.json")["constraints"]
    assert run.parent().frozen
