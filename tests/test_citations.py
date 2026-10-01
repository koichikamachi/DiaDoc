"""出典の照合：発言の数字が引用した頁に本当にあるか（core.citations）。本物の Gemini は呼ばない。"""

from __future__ import annotations

import pytest

from agents.base import DebateContext
from core import citations as c
from core.graph import formal_review
from core.runs import latest_run
from schema import DebateMessage, SourceRef
from state import initial_state

FS, MEMO = "決算報告書第62期（架空）", "ヒアリングメモ_第62期（架空）"


@pytest.fixture(scope="module")
def ctx():
    return DebateContext.from_run(latest_run("C002_sample_crisis"))


@pytest.fixture(scope="module")
def idx(ctx):
    return c.build_index(ctx.fin, ctx.materials)


def S(f, p):
    return SourceRef(file=f, page=p)


def test_extract_units_and_ratios():
    figs = {(f.kind, round(f.value, 4)) for f in c.extract("売上の約6割、5%の値上げ、1.8億円、24,000千円、3か月、78名、1962年")}
    assert figs == {("wari", 0.6), ("pct", 0.05), ("amount", 180_000.0), ("amount", 24_000.0)}


def test_memo_is_split_by_page_marks(idx):
    assert {p for (d, p) in idx if d == MEMO} == {"1", "2", "3"}
    assert idx[(MEMO, "3")].has(c.extract("短期借入金180,000千円")[0])


@pytest.mark.parametrize("text,src", [
    ("最大顧客が売上の約6割を占める。", S(MEMO, "1")),                          # 正しい出典
    ("売上高1,180,000千円に5%の値上げで年59,000千円の増収。", S(FS, "3")),       # 計算した数字は咎めない
    ("短期借入金1.8億円の折り返しが焦点。", S(MEMO, "3")),                        # 単位が違っても同じ額
    ("営業利益率は-4.7%で、材料費率は49.1%。", S(FS, "3")),                      # 決算書から計算した百分率
])
def test_correct_or_derived_figures_pass(idx, text, src):
    assert c.check(text, [src], idx) == []


def test_the_six_tenths_mixup_is_caught(idx):
    """実機の Gemini で起きた取り違え：ヒアリングメモの「6割」を決算報告書 p.3 として引いた。"""
    probs = c.check("最大顧客が売上の約6割を占めるため、値上げ交渉は慎重に。", [S(FS, "3")], idx)
    assert len(probs) == 1 and "「6割」" in probs[0] and f"{MEMO} p.1にあります" in probs[0]


def test_amount_from_the_memo_cited_as_financials(idx):
    probs = c.check("段取り替えで年24,000千円の労務費を減らせる。", [S(FS, "4")], idx)
    assert probs and f"{MEMO} p.2" in probs[0]


def test_formal_review_sends_back_a_mixup(ctx):
    st = initial_state("C002_sample_crisis", "run_001_initial", ctx.base)
    m = DebateMessage(id="R1-growth-1", round=1, phase="exploration", speaker="growth", action="提示",
                      text="最大顧客が売上の約6割を占めるため、値上げ交渉は慎重に進める。",
                      sources=[S(FS, "3")], settle_condition="10月の単価交渉の結果")
    assert formal_review(m, st, ctx.registry).verdict == "通過"                 # 照合なし＝以前の挙動
    r = formal_review(m, st, ctx.registry, ctx.citation_index())
    assert r.verdict == "差し戻し" and "根拠の頁の取り違え" in r.reasons[0]


# ---------------------------------------------------------------------------
# 実機の Gemini が書いた発言（2026-09-27〜28 の試運転の記録から）で確かめる
# ---------------------------------------------------------------------------
import json  # noqa: E402
from pathlib import Path  # noqa: E402

from core.runs import Run  # noqa: E402

REAL = json.loads((Path(__file__).parent / "fixtures/gemini_citations.json").read_text(encoding="utf-8"))


def _real(key):
    comp = key.split(":")[0]
    ctx = DebateContext.from_run(Run(comp, "run_001_initial"))
    m = REAL[key]
    srcs = [SourceRef(file=ctx.resolve_source(s["file"]), page=str(s["page"])) for s in m["sources"]]
    return c.check(m["text"], srcs, ctx.citation_index())


def test_real_gemini_six_tenths_inline_mixup():
    """「売上の約6割を占める最大顧客（決算報告書 p.3 の売上…）」：6割を決算報告書の頁に結びつけている。"""
    probs = _real("C002_sample_crisis:growth:2")
    assert len(probs) == 1 and "「6割」" in probs[0] and "ヒアリングメモ_第62期（架空） p.1" in probs[0]


def test_real_gemini_memo_amount_cited_as_financials():
    probs = _real("C002_sample_crisis:radar:2")
    assert len(probs) == 1 and "「24,000千円」" in probs[0] and "決算報告書第62期（架空） p.4にはなく" in probs[0]


@pytest.mark.parametrize("key", ["C002_sample_crisis:rebuild:3",      # 一つの括弧に二つの出典
                                 "C001_sample_alpha:rebuild:1"])   # 括弧の中で数字の後に資料名
def test_real_gemini_correct_citations_are_not_flagged(key):
    assert _real(key) == []


def test_sheet_name_pages_count_as_cited():
    """Excel の決算書はシート名が頁になる（p.貸借対照表）。面談メモと一緒に引いても、決算書の数字を取り違え扱いしない。
    （2026-10-01、乙精機ケース3：長期借入金100,000千円が「面談メモ p.1 にない」として差し戻されていた）"""
    from schema import Financials, LineItem

    XL, MEMO3 = "乙精機_第10期_A_一致.xlsx", "乙精機_面談メモ"
    fin = Financials(company_id="C9", fiscal_period="第10期", basis="単体", items={
        "ltd": LineItem(statement="BS", section="固定負債", label="長期借入金", cur=100_000,
                        source=SourceRef(file=XL, page="貸借対照表")),
        "lab": LineItem(statement="CR", section="労務費", label="労務費", cur=60_000,
                        source=SourceRef(file=XL, page="損益計算書")),
    })
    idx = c.build_index(fin, {MEMO3: "- 工場長：設備の老朽化で、年2回ほどライン停止が起きている。"})
    text = ("年2回のライン停止（乙精機_面談メモ p.1）の事実のみ扱います。長期借入金100,000千円（乙精機_第10期_A_一致.xlsx p.貸借対照表）"
            "は返済区分がなく、労務費60,000千円（同 p.損益計算書）の稼働ロスも疑われます。")
    srcs = [S(XL, "貸借対照表"), S(XL, "損益計算書"), S(MEMO3, "1")]
    assert c.check(text, srcs, idx) == []
    # 本当の取り違え（決算書の数字を面談メモだけで引いた）は、引き続き捕まえる
    probs = c.check("長期借入金100,000千円が重い（乙精機_面談メモ p.1）。", [S(MEMO3, "1")], idx)
    assert probs and f"{XL} p.貸借対照表にあります" in probs[0]
