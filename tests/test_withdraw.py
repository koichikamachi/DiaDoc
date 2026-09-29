"""投入済み資料の取り下げ。消さずに保管し、採用済みの数値や見本・引き継ぎ資料は守る。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.mock_engine import handle_upload, withdraw_input, withdrawable
from core.runs import create_company, latest_run, list_runs
from test_new_company import RealLike

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_duplicate_is_moved_aside_and_logged(data):
    handle_upload("C001_sample_alpha", "勘定科目内訳明細書.pdf", b"%PDF")
    run, _, _ = handle_upload("C001_sample_alpha", "勘定科目内訳明細書.pdf", b"%PDF")
    touched = [r["id"] for r in run.read("data_requests.json") if any(x["file"].endswith("_2.pdf") for x in r.get("received", []))]
    assert touched
    dup = run.path / "inputs" / "勘定科目内訳明細書_2.pdf"
    assert withdrawable(run, dup) == (True, "")
    msg = withdraw_input(run, dup.name)
    assert "取り下げ" in msg and not dup.exists()
    kept = list((run.path / "withdrawn").glob("*勘定科目内訳明細書_2*"))
    assert any(p.suffix == ".pdf" for p in kept)                       # 消さずに保管
    assert not (run.path / "extracted" / "勘定科目内訳明細書_2.json").exists()
    assert run.read("audit_log.json")[-1]["file"] == dup.name
    assert run.read("debate_log.json")[-1]["text"].startswith("投入資料を取り下げ")
    reqs = {r["id"]: r for r in run.read("data_requests.json")}
    assert all(x["file"] != dup.name for r in reqs.values() for x in r.get("received", []))
    assert all(reqs[k]["status"] == "受領（検証待ち）" and reqs[k]["received"] for k in touched)   # 最初の受領は生きている


def test_withdrawing_the_only_receipt_reverts_the_request(data):
    run, _, _ = handle_upload("C001_sample_alpha", "勘定科目内訳明細書.pdf", b"%PDF")
    before = {r["id"]: r["status"] for r in run.read("data_requests.json")}
    withdraw_input(run, "勘定科目内訳明細書.pdf")
    after = {r["id"]: r["status"] for r in run.read("data_requests.json")}
    changed = [k for k in before if before[k] == "受領（検証待ち）" and after[k] == "請求中"]
    assert changed


def test_adopted_statement_cannot_be_withdrawn(data):
    company = create_company("甲")
    run, _, _ = handle_upload(company, "第24期.pdf", b"%PDF", extractor=RealLike())
    ok, why = withdrawable(run, run.path / "inputs" / "第24期.pdf")
    assert not ok and "採用済み" in why
    with pytest.raises(ValueError):
        withdraw_input(run, "第24期.pdf")
    assert (run.path / "inputs" / "第24期.pdf").exists()


def test_bundled_inherited_and_frozen_documents_are_protected(data):
    run = latest_run("C002_sample_crisis")
    memo = run.path / "inputs" / "hearing_memo_62.md"
    assert withdrawable(run, memo)[0] is False                           # 同梱の見本
    assert withdrawable(run, None)[0] is False                           # ファイルのない出典書類
    new, _, _ = handle_upload("C002_sample_crisis", "勘定科目内訳明細書.pdf", b"%PDF")
    first = list_runs("C002_sample_crisis")[0]
    assert first.frozen and not withdrawable(first, first.path / "inputs" / "hearing_memo_62.md")[0]
    assert not withdrawable(new, memo)[0]                                # 親の回次から引き継いだ資料


def test_adopted_excel_is_listed_once_as_a_financial_document(data):
    from core import digest
    from core.graph import DebateSession

    company = create_company("丙")
    run, _, _ = handle_upload(company, "財務諸表_丙_第5期.xlsx", b"PK", extractor=RealLike())
    s = DebateSession(run)
    docs = digest.documents(run, s.ctx, None)
    assert [(d.name, d.kind) for d in docs] == [("財務諸表_丙_第5期.xlsx", "財務")]      # 出典書類と投入ファイルを1行に
    assert docs[0].path == run.path / "inputs" / "財務諸表_丙_第5期.xlsx"
    ok, why = withdrawable(run, docs[0].path)
    assert not ok and "採用済み" in why


def test_document_kind_follows_the_name_not_the_extension():
    from core.digest import _kind

    assert _kind("財務諸表_甲_第24期.xlsx", "財務諸表_甲_第24期") == "財務"
    assert _kind("standard_mapping_check_73.xlsx", "標準科目対応_検算_第73期単体") == "検算表"
    assert _kind("memo.md", "面談メモ") == "定性"


def test_mock_reason_names_the_real_cause(monkeypatch):
    import config

    monkeypatch.setenv("DBD_EXTRACTOR", "mock")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-for-test")
    assert "DBD_EXTRACTOR=mock" in config.mock_reason()
    monkeypatch.delenv("DBD_EXTRACTOR")
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert config.mock_reason() == "GEMINI_API_KEY 未設定"
