"""財務・4P突合マトリクスの指標（core.indicators）。数字の出どころ（計算式・内訳・出典頁）を必ず持つ。"""

from __future__ import annotations

import pytest

from core import indicators as ind
from core.runs import latest_run


@pytest.fixture(scope="module")
def alpha():
    return latest_run("C001_sample_alpha").financials()


@pytest.fixture(scope="module")
def crisis():
    return latest_run("C002_sample_crisis").financials()


def test_kpis_are_common_plus_company_specific(alpha, crisis):
    common = [i.key for i in ind.COMMON]
    assert [i.key for i in ind.kpis(alpha)] == common + ["div_dep", "purchase_ratio"]
    assert [i.key for i in ind.kpis(crisis)] == common + ["purchase_ratio"]   # 経常赤字なので受取配当依存は出さない


def test_op_margin_carries_formula_basis_and_pages(alpha):
    v = ind.evaluate(alpha, next(i for i in ind.COMMON if i.key == "op_margin"))
    assert v.cur == pytest.approx(648_638 / 28_148_648)
    assert "営業利益 648,638（有報第73期（モデル） p.93）" in v.basis and "÷ 売上高 28,148,648（有報第73期（モデル） p.93）" in v.basis
    assert ind.delta_text(v).startswith("-") and ind.delta_text(v).endswith("pt（前期比）")


def test_amount_delta_is_a_rate_not_the_previous_value(alpha):
    v = ind.evaluate(alpha, next(i for i in ind.COMMON if i.key == "sales"))
    assert ind.delta_text(v) == f"{28_148_648 / 24_298_452 - 1:+.1%}（前期比）"
    assert ind.fmt(v.ind, v.cur) == "281.5億円"


def test_debt_includes_short_term_borrowings(crisis):
    v = ind.evaluate(crisis, next(i for i in ind.COMMON if i.key == "debt"))
    assert v.cur == 180_000 + 96_000 + 312_000 + 4_800 + 9_600
    assert "短期借入金 180,000（決算報告書第62期（架空） p.2）" in v.basis


def test_real_mode_uses_the_estimated_balance_sheet(alpha):
    er = next(i for i in ind.COMMON if i.key == "equity_ratio")
    nom, real = ind.evaluate(alpha, er, "nominal"), ind.evaluate(alpha, er, "real")
    assert nom.cur != real.cur and real.prev is None and real.note.startswith("実質BS：推計")


def test_ratio_rows_have_no_hardcoded_pages(crisis):
    rows = [ind.evaluate(crisis, i) for i in ind.RATIOS]
    assert all("p.93" not in v.basis for v in rows)                          # C001 の頁が他社に出ない
    mat = next(v for v in rows if v.ind.key == "mat_ratio")
    assert mat.cur == pytest.approx(520_000 / 1_060_000) and "p.4" in mat.basis


def test_current_ratio_is_in_the_table_but_not_in_the_chart(crisis):
    cr = next(i for i in ind.RATIOS if i.key == "current_ratio")
    v = ind.evaluate(crisis, cr)
    assert not cr.chart and v.cur == pytest.approx(crisis.value("tca") / crisis.value("tcl"))


def test_sample_companies_compare_with_the_official_sme_survey():
    from core.runs import load_benchmarks

    for company in ("C001_sample_alpha", "C002_sample_crisis"):
        b = load_benchmarks(company)
        ind_ = b["industry"]
        assert ind_ and not ind_.get("placeholder") and ind_["source"] == "中小企業実態基本調査（製造業統計）"
        assert ind_["ratios"] == {"op_margin": 0.032, "equity_ratio": 0.415, "current_ratio": 1.48}
        assert b["peers"] == []
