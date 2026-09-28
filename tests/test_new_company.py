"""新しい対象会社、最初の財務書類の格納、検算不一致の扱い、発言者の指名。本物の Gemini は呼ばない。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core.graph import DebateSession
from core.mock_engine import handle_upload
from core.runs import create_company, latest_run, list_companies, list_runs
from tools.file_ingest import Extraction, MockExtractor

ROOT = Path(__file__).resolve().parents[1]
CRISIS_FIN = ROOT / "data/companies/C002_sample_crisis/runs/run_001_initial/inputs/financials.json"


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


class RealLike(MockExtractor):
    """実際の読み取りに見せかけた抽出器（中身は C002 の検算済みデータ）。"""

    name = "gemini:fake"

    def __init__(self, break_total: bool = False):
        super().__init__(CRISIS_FIN)
        self.break_total = break_total

    def extract(self, filename: str, content: bytes) -> Extraction:
        ex = super().extract(filename, content)
        if self.break_total:   # 資産合計を1,000千円ずらして、検算を不一致にする
            for it in ex.items:
                if it.key == "ta":
                    it.cur += 1000
        return ex


# ---------------------------------------------------------------------------
# 新しい対象会社
# ---------------------------------------------------------------------------
def test_create_company_makes_an_empty_first_run(data):
    company = create_company("サンプル精工", "金属製品製造", fictional=True, mission="事業計画の骨子づくり")
    assert company.startswith("C003_")
    meta = json.loads((data / "companies" / company / "meta.json").read_text(encoding="utf-8"))
    assert meta["fictional"] is True and meta["mission"] == "事業計画の骨子づくり" and "架空モデル" in meta["display_name"]
    runs = list_runs(company)
    assert [r.run_id for r in runs] == ["run_001_initial"] and not runs[0].frozen and runs[0].financials() is None
    assert company in {c["dir"] for c in list_companies()}
    s = DebateSession(runs[0])
    assert s.ctx.fin is None and s.ctx.mission == "事業計画の骨子づくり"


def test_company_name_is_required(data):
    with pytest.raises(ValueError):
        create_company("  ")


def test_first_financial_statements_go_into_the_empty_first_run(data):
    company = create_company("サンプル精工")
    run, added, opened = handle_upload(company, "決算報告書.pdf", b"%PDF", extractor=RealLike())
    assert not opened and run.run_id == "run_001_initial" and len(list_runs(company)) == 1
    fin = run.financials()
    assert fin is not None and fin.items["cash"].cur == 51_000
    assert "論争を始められます" in added[-2]["text"]


def test_mock_reading_is_never_adopted_as_the_companys_data(data):
    company = create_company("サンプル精工")
    run, _, _ = handle_upload(company, "決算報告書.pdf", b"%PDF", extractor=MockExtractor())
    assert run.run_id == "run_001_initial" and run.financials() is None   # アルファのサンプルを別会社のデータにしない


def test_mismatch_is_reported_and_not_adopted(data):
    company = create_company("サンプル精工")
    run, added, _ = handle_upload(company, "決算報告書.pdf", b"%PDF", extractor=RealLike(break_total=True))
    assert run.financials() is None
    rec = json.loads(next((run.path / "extracted").glob("*.json")).read_text(encoding="utf-8"))
    assert rec["gate"] == "停止"
    names = {(r["name"], r["period"]) for r in rec["failed_checks"]}
    assert ("資産合計", "当期") in names
    row = next(r for r in rec["failed_checks"] if r["name"] == "資産合計")
    assert row["diff"] == -1000                                   # 計算値−報告値
    assert any("検算ゲートで一致しません" in m["text"] for m in added)


def test_second_upload_into_the_first_run_after_data_exists_opens_the_next_run(data):
    company = create_company("サンプル精工")
    handle_upload(company, "決算報告書.pdf", b"%PDF", extractor=RealLike())
    run, _, opened = handle_upload(company, "勘定科目内訳明細書.pdf", b"%PDF", extractor=MockExtractor())
    assert opened and run.run_id == "run_002_followup"           # 従来どおりの回次の規則


def test_new_company_debate_runs_once_data_is_in(data):
    company = create_company("サンプル精工", mission="資金繰りの確認")
    handle_upload(company, "決算報告書.pdf", b"%PDF", extractor=RealLike())
    s = DebateSession(latest_run(company))
    s.step()
    st = s.state()
    assert st.mission == "資金繰りの確認" and st.monitor.base.required_cf == 122_090
    assert st.messages[0].speaker == "radar"                      # 台本のない会社では「台本がありません」の発言


# ---------------------------------------------------------------------------
# 発言者の指名
# ---------------------------------------------------------------------------
def test_nominated_speaker_jumps_in_and_the_order_resumes(data):
    s = DebateSession(latest_run("C002_sample_crisis"))
    s.step(), s.step()                                            # radar, growth
    assert s.next_node == "rebuild"
    new = s.step("radar")
    assert [m.speaker for m in new] == ["radar"] and s.next_node == "rebuild"
    s.step()                                                      # rebuild
    assert s.next_node == "judge"
    new = s.step("growth")                                        # Judge の番に割り込む
    assert [m.speaker for m in new] == ["growth"] and s.next_node == "judge"
    s.step()
    ruled = {r.message_id for r in s.state().rulings}
    assert new[0].id in ruled                                     # 指名発言も同じラウンドで審理される


def test_nominating_the_current_speaker_is_just_a_normal_step(data):
    s = DebateSession(latest_run("C002_sample_crisis"))
    s.step()
    assert [m.speaker for m in s.step("growth")] == ["growth"] and s.next_node == "rebuild"


def test_nomination_is_only_for_the_exploration_phase(data):
    s = DebateSession(latest_run("C002_sample_crisis"))
    while s.state() is None or s.state().phase == "exploration":
        s.step()
    assert s.state().phase == "triage_ready" and not s.can_nominate()
    with pytest.raises(ValueError):
        s.step("growth")
    with pytest.raises(ValueError):
        DebateSession(latest_run("C001_sample_alpha")).step("judge")


# ---------------------------------------------------------------------------
# 資料のプレビューと回次の比較
# ---------------------------------------------------------------------------
def test_document_items_lists_the_statements_with_pages(data):
    from core.digest import document_items

    fin = latest_run("C002_sample_crisis").financials()
    rows = document_items(fin, "決算報告書第62期（架空）")
    cash = next(r for r in rows if r["key"] == "cash")
    assert cash["当期"] == 51_000 and cash["頁"] == "2" and rows[0]["表"] == "BS"
    assert document_items(fin, "存在しない資料") == []


def test_documents_carry_paths_and_urls(data):
    from core.digest import documents

    s = DebateSession(latest_run("C001_sample_alpha"))
    docs = {d.name: d for d in documents(s.run, s.ctx)}
    assert docs["有報第73期"].url.startswith("https://") and docs["有報第73期"].path is None
    xl = next(d for d in docs.values() if d.kind == "検算表")
    assert xl.path.exists()


def test_run_comparison_reads_frozen_runs_without_touching_them(data):
    from core.digest import compare_runs
    from core.runs import start_next_run

    first = DebateSession(latest_run("C002_sample_crisis"))
    while not first.finished:
        first.step()
    first.adopt("（二）看板維持型（返済猶予で時間を買う）", "メインバンクが3か月の猶予に応諾")
    first.close()
    second = start_next_run("C002_sample_crisis", "やり直し")          # 第1次を凍結
    db = list_runs("C002_sample_crisis")[0].path / "checkpoints.sqlite"
    before = db.stat().st_mtime
    s2 = DebateSession(second)
    s2.run_round()
    rows = {r["物差し"]: r for r in compare_runs(list_runs("C002_sample_crisis"))}
    cols = [k for k in rows["状態"] if k != "物差し"]
    assert [rows["状態"][c] for c in cols] == ["凍結", "作業中"]
    assert "トリアージ宣告" in rows["最終フェーズ"][cols[0]] and "進行中" in rows["最終フェーズ"][cols[1]]
    assert rows["試した改善レバー"][cols[0]] == "売上・粗利・原価・現場・固定費・販管費・資産売却・BS"
    assert rows["採択された方針"][cols[0]].startswith("（二）看板維持型")
    assert db.stat().st_mtime == before                                # 凍結した回次のファイルは変わらない


def test_adoption_requires_a_closed_debate(data):
    s = DebateSession(latest_run("C002_sample_crisis"))
    s.step()
    with pytest.raises(ValueError):
        s.adopt("（一）")
