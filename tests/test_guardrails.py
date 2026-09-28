"""検算ゲートと形式審査のテスト（決定論的部分、LLM不使用）。

制作サンプル：アルファ製菓 第73期 単体（data/companies/C001_sample_alpha/runs/run_001_initial）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.guardrails import CHECKS, parse_source, reconcile, review_claim, tolerance
from schema import Claim, Financials, SourceRef

ROOT = Path(__file__).resolve().parents[1]
FIN_PATH = ROOT / "data/companies/C001_sample_alpha/runs/run_001_initial/inputs/financials.json"


@pytest.fixture()
def fin() -> Financials:
    return Financials.model_validate(json.loads(FIN_PATH.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# 許容差の規則
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("n", "expected"), [(0, 2), (1, 2), (2, 2), (3, 3), (9, 9), (13, 13)])
def test_tolerance_is_component_count_with_floor_of_two(n, expected):
    assert tolerance(n, "truncate_thousand") == expected


def test_tolerance_is_zero_for_yen_documents():
    assert tolerance(13, "yen") == 0


# ---------------------------------------------------------------------------
# 制作サンプルで全項目一致
# ---------------------------------------------------------------------------
def test_sample_has_38_checks():
    assert len(CHECKS) == 38


def test_sample_reconciles_all_items(fin):
    report = reconcile(fin)
    failed = [(c.name, [(p.period, p.diff, p.tolerance) for p in c.periods]) for c in report.checks if c.status != "一致"]
    assert failed == []
    assert report.total == 38
    assert report.count("一致") == 38
    assert report.count("不一致") == 0
    assert report.passed


def test_sample_rounding_differences_are_within_component_count(fin):
    report = reconcile(fin)
    assert report.rounding_diffs == 34
    current_liabilities = next(c for c in report.checks if c.name == "流動負債合計")
    prev = next(p for p in current_liabilities.periods if p.period == "prev")
    assert prev.diff == -6 and prev.tolerance == 13  # 13件の内訳で6千円のずれ → 許容内


def test_fixed_two_thousand_rule_would_have_wrongly_stopped(fin):
    """一律2千円の許容差だと、正しい決算書でも不一致として止まってしまうことを確認する。"""
    report = reconcile(fin)
    would_fail = [c.name for c in report.checks for p in c.periods if p.diff is not None and abs(p.diff) > 2]
    assert set(would_fail) >= {"流動資産合計", "有形固定資産合計", "流動負債合計", "固定負債合計"}


# ---------------------------------------------------------------------------
# 誤りを検出して止まること
# ---------------------------------------------------------------------------
def test_gate_stops_on_transcription_error(fin):
    fin.items["cash"].cur += 20  # 読み取り誤りを模す（20千円）
    report = reconcile(fin)
    assert not report.passed
    assert {c.name for c in report.checks if c.status == "不一致"} == {"流動資産合計"}


def test_gate_detects_cross_statement_break(fin):
    fin.items["ewip"].cur += 10  # 製造原価明細書の期末仕掛品だけ誤読
    report = reconcile(fin)
    names = {c.name for c in report.checks if c.status == "不一致"}
    assert "貸借対照表の仕掛品＝製造原価の期末仕掛品" in names
    assert "当期製品製造原価" in names


def test_gate_detects_opening_balance_break(fin):
    fin.items["re"].prev += 100  # 前期末の繰越利益剰余金だけ誤読
    report = reconcile(fin)
    names = {c.name for c in report.checks if c.status == "不一致"}
    assert "繰越利益剰余金の動き（前期末＋純利益−配当−別途積立＝当期末）" in names


def test_missing_item_is_unverified_not_passed(fin):
    fin.items["oca"].cur = None
    report = reconcile(fin)
    check = next(c for c in report.checks if c.name == "流動資産合計")
    assert check.status == "未確認"
    assert "oca" in check.missing


def test_yen_documents_allow_no_rounding_difference(fin):
    fin.rounding = "yen"
    report = reconcile(fin)
    assert not report.passed  # 千円単位の端数差は円単位の書類では許されない


# ---------------------------------------------------------------------------
# 形式審査
# ---------------------------------------------------------------------------
SRC = SourceRef(file="有報第73期", page="94")


def test_review_rejects_claim_without_source():
    r = review_claim(Claim(speaker="growth", text="増収は自社ブランド力の表れ", settle_condition="自社製品売上の前期比"))
    assert r.verdict == "退け"


def test_review_rejects_source_without_page():
    r = review_claim(Claim(speaker="growth", text="…", sources=[SourceRef(file="有報第73期")], settle_condition="…の比較"))
    assert r.verdict == "退け"
    assert "頁" in r.reasons[0]


def test_review_returns_claim_without_settle_condition():
    r = review_claim(Claim(speaker="growth", text="増収は自社ブランド力の表れ", sources=[SRC]))
    assert r.verdict == "差し戻し"


@pytest.mark.parametrize("trivial", ["", "  ", "なし", "不明", "-"])
def test_review_treats_trivial_settle_condition_as_missing(trivial):
    r = review_claim(Claim(speaker="x", text="…", sources=[SRC], settle_condition=trivial))
    assert r.verdict == "差し戻し"


def test_review_passes_claim_with_source_and_settle_condition():
    r = review_claim(Claim(speaker="growth", text="価格転嫁は機能している", sources=[SRC],
                           settle_condition="自社製品売上の前期比と主力品粗利率"))
    assert r.verdict == "通過"
    assert r.valid_sources == [SRC]


def test_review_ignores_incomplete_sources_when_a_valid_one_exists():
    r = review_claim(Claim(speaker="x", text="…", sources=[SourceRef(file="業界紙"), SRC], settle_condition="…"))
    assert r.verdict == "通過"
    assert r.valid_sources == [SRC]


@pytest.mark.parametrize(("text", "file", "page"), [
    ("有報第73期 p.93", "有報第73期", "93"),
    ("有報第73期 p.91–92", "有報第73期", "91–92"),
    ("勘定科目内訳明細書 3頁", "勘定科目内訳明細書", "3"),
    ("市況メモ", "市況メモ", None),
])
def test_parse_source(text, file, page):
    s = parse_source(text)
    assert (s.file, s.page) == (file, page)
