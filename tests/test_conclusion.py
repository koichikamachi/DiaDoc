"""結論の見せ方（2026-09-30）：回次の状態表示の統一、決着時のサマリーバナー、診断レポート（Markdown）。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core import conclusion
from core.graph import DebateSession
from core.metrics import cash_base, project
from core.mock_engine import report_markdown
from core.runs import latest_run
from schema import CausalBridge, DebateMessage, Ruling, SourceRef
from state import DebateState

ROOT = Path(__file__).resolve().parents[1]
CRISIS = "C002_sample_crisis"
SRC = [SourceRef(file="決算報告書", page="3")]


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _finish(s):
    for _ in range(40):
        if s.finished:
            return s.state()
        s.step()
    raise AssertionError("論争が終わらない")


# ---------------------------------------------------------------------------
# 1. 回次の状態表示
# ---------------------------------------------------------------------------
def test_status_label_is_one_thing_at_a_time(data):
    run = latest_run(CRISIS)
    s = DebateSession(run)
    assert conclusion.run_heading(run, s.state()) == "第1次分析（未開始）"
    s.step()
    assert conclusion.run_heading(run, s.state()) == "第1次分析（進行中：第1ラウンド）"
    s.run_round()
    assert conclusion.run_heading(run, s.state()) == "第1次分析（進行中：第2ラウンド）"
    st = _finish(s)
    head = conclusion.run_heading(run, st)
    assert head == "第1次分析（診断完了・トリアージ宣告）"
    assert "作業中" not in head and "決着" not in head.replace("充足決着", "")


@pytest.mark.parametrize("reason,kind", [("改善策で充足", "充足決着"), ("トリアージ宣告", "トリアージ宣告"),
                                         ("膠着（資金不足なし）", "資金不足なし"),
                                         ("判定保留（返済予定表の開示待ち）", "要追加検討"),
                                         ("膠着（資金データ不足）", "要追加検討"), ("宣告不成立（上限到達）", "要追加検討")])
def test_outcome_kinds(reason, kind):
    st = _state(stop=reason)
    assert conclusion.outcome(st).kind == kind


def test_limit_reached_without_shortage_is_no_shortage_but_with_gap_needs_more():
    ok = _state(stop="上限到達", base=_base(debt=0))
    assert conclusion.outcome(ok).kind == "資金不足なし"
    short = _state(stop="上限到達", base=_base(debt=10_000))
    assert conclusion.outcome(short).kind == "要追加検討"


def test_frozen_run_says_so(data):
    from core.mock_engine import start_manual_run

    run = latest_run(CRISIS)
    _finish(DebateSession(run))
    start_manual_run(CRISIS)
    old = [r for r in __import__("core.runs", fromlist=["list_runs"]).list_runs(CRISIS) if r.frozen][0]
    from core.digest import load_state

    assert conclusion.run_heading(old, load_state(old)) == "第1次分析（凍結・閲覧のみ／診断完了・トリアージ宣告）"


# ---------------------------------------------------------------------------
# 2. 決着時のサマリーバナー
# ---------------------------------------------------------------------------
def _base(debt=10_000):
    """乙精機ケースBの資金の姿：簡易営業CF 8,630。返済予定表で年間返済を確定した後。"""
    from core.repayment import Repayment
    from test_debt_pending import _fin

    rp = Repayment(amount=debt, basis="〇〇銀行の返済予定表を確認", at="2026-09-30T10:00:00") if debt is not None else None
    return cash_base(_fin(), rp)


def _state(stop, base=None):
    base = base or _base()
    prop = DebateMessage(id="R2-growth-6", round=2, phase="exploration", speaker="growth", action="提案",
                         headline="労務費の削減と有価証券の売却", text="労務費を年1,500千円削る。投資有価証券500千円を売る。",
                         sources=SRC, settle_condition="人員計画",
                         bridges=[CausalBridge(account="lab", direction="減", amount=1_500, cf_effect=1_500, lead_months=3),
                                  CausalBridge(account="inv", direction="減", amount=500, cf_effect=500, lead_months=1,
                                               recurring=False)])
    rulings = [Ruling(message_id=prop.id, round=2, verdict="通過")]
    tmp = DebateState(company_id="C", run_id="r", monitor=project(base, []), messages=[prop], rulings=rulings)
    mon = project(base, tmp.passed_bridges(), 0, 2)
    return tmp.model_copy(update={"monitor": mon, "phase": "settlement", "next_speaker": None, "stop_reason": stop,
                                  "round": 2})


def test_goal_banner_for_a_sufficient_plan():
    st = _state("改善策で充足")
    b = conclusion.banner(st, st.monitor.base, [{"id": "R1", "item": "借入金返済予定表", "status": "解消"}])
    assert b.tone == "success"
    assert b.title == "診断完了：必要CF（年間 1,370千円）の確保シナリオが策定されました"
    text = "\n".join(b.lines)
    assert "確定した約定返済：年10,000" in text and "〇〇銀行の返済予定表" in text
    assert "労務費の削減と有価証券の売却（年1,500千円・3か月後から）" in text
    assert "一括調達（一時的資金）：500千円" in text
    assert "未解決の宿題" not in text                                              # 宿題はすべて解消済み


def test_goal_banner_for_more_work_names_what_is_missing():
    st = _state("判定保留（返済予定表の開示待ち）", base=_base(debt=None).model_copy(
        update={"debt_unverified": ["長期借入金 100,000千円に1年内返済の区分がない"], "ref_debt_service": 10_000,
                "ref_free_cf": -1_370, "debt_confirmed": ""}))
    b = conclusion.banner(st, st.monitor.base, [{"id": "R1", "item": "借入金返済予定表", "status": "請求中",
                                                "required": True}])
    assert b.tone == "warning" and b.title.startswith("診断完了（要追加検討）")
    text = "\n".join(b.lines)
    assert "判定保留" in text and "△1,370" in text and "未解決の宿題：1件（うち必須1件）" in text
    assert "未着手のレバー：売上・粗利／原価・現場／固定費・販管費／資産売却・BS" in text


def test_no_banner_while_the_debate_is_running():
    st = _state("改善策で充足").model_copy(update={"phase": "exploration", "next_speaker": "radar", "stop_reason": None})
    assert conclusion.banner(st, st.monitor.base) is None


# ---------------------------------------------------------------------------
# 3. 診断レポート
# ---------------------------------------------------------------------------
SECTIONS = ("## 1. エグゼクティブサマリー", "## 2. 前提条件と監査的オーバーライド（人間介入）",
            "## 3. 採択された改善シナリオ一覧", "## 4. 残されたリスク・未決争点", "## 5. データ請求（宿題リスト）")


def test_report_of_a_finished_debate_has_every_section_filled(data):
    run = latest_run(CRISIS)
    _finish(DebateSession(run))
    md = report_markdown(run)
    assert md.startswith("# 経営診断レポート：C002_架空モデル（窮境・金属プレス部品）（第1次分析）")
    assert "- **診断適格性（DDF）**：適格（Fit）" in md and "- **結論フェーズ**：診断完了・トリアージ宣告" in md
    idx = [md.index(h) for h in SECTIONS]
    assert idx == sorted(idx)
    assert "必要CFは年122,090千円" in md and "継続改善CFは年30,000千円" in md
    assert "| 値上げと段取り替えの同時実施 | 労務費（減） | +24,000 |" in md
    assert "### 【一括調達（一時的資金）】" in md and "+4,000" in md
    assert "（一）雇用死守型の第二会社方式" in md
    assert "Dr. Rebuild の反論（攻撃）とその扱い" in md and "R1-growth-2 技術とブランドで再生（定性）" in md
    assert "**未着手のレバー**：なし（4つすべて試した）" in md


def test_report_lists_overrides_and_resolved_homework(data):
    from core import adjust, repayment
    from core.mock_engine import ensure_debt_request, handle_upload
    from core.runs import create_company
    from test_ddf import _Fixed, _lines

    company = create_company("丁工業", fictional=True)
    run, _, _ = handle_upload(company, "丁.xlsx", b"x", extractor=_Fixed(_lines(sga_reported=49_800)))
    adjust.add(run, "土地", "有形・無形固定資産", 100_000, "近隣の相場を聞き取りした", "land")
    repayment.confirm(run, 6_000, "〇〇銀行の返済予定表を確認")
    ensure_debt_request(run)
    md = report_markdown(run)
    assert "〔人間 A1〕土地 +100,000千円" in md and "近隣の相場を聞き取りした" in md
    assert "- **約定返済額の確定**：年間約定返済額 6,000千円（根拠：〇〇銀行の返済予定表を確認）" in md
    part = md[md.index("## 5."):]
    assert "**解消済み**" in part and "【必須】借入金返済予定表：解消" in part and "証跡：年間約定返済額（人間が返済予定表で確定） 6,000" in part
    assert "- **結論フェーズ**：未開始" in md


def test_report_shows_reduced_adoption(data):
    """反論で減額採択になった提案は、元の額・減額後・理由をレポートに書く。"""
    s = DebateSession(latest_run(CRISIS))
    s.run_round()
    s.step()
    s.step()
    growth = s.state().messages[-1]
    first = growth.bridges[0]
    s.ctx.script["rebuild"]["exploration"][1].update(
        target_message=growth.id, challenged_account=first.account, feasible_cf=first.cf_effect // 2)
    s.run_round()
    md = report_markdown(latest_run(CRISIS))
    part = md[md.index("### 減額採択（▽）"):]
    assert f"{first.cf_effect:,} → {first.cf_effect // 2:,}" in part and "理由：減額採択" in part


def test_sidebar_download_and_header_use_the_new_wording(data):
    from streamlit.testing.v1 import AppTest

    _finish(DebateSession(latest_run(CRISIS)))
    at = AppTest.from_file(str(ROOT / "src/ui/app.py"), default_timeout=30)
    at.run()
    at.selectbox(key="company").set_value(CRISIS).run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "第1次分析（診断完了・トリアージ宣告）" in text and "作業中" not in text
    errs = [e.value for e in at.error]
    assert any("トリアージを宣告しました" in e for e in errs)                        # ゴールテープ（赤系）
    labels = at.selectbox(key="run_select__" + CRISIS)
    assert "診断完了・トリアージ宣告" in labels.format_func(labels.value)


def test_report_opens_with_an_abstract_that_stands_alone(data):
    """冒頭の「要約」だけで、何の診断か・結論・理由・次に要ることが分かる（新聞のリード、論文の要約）。"""
    run = latest_run(CRISIS)
    md = report_markdown(run)
    head = md[md.index("## 要約"):md.index("## 1. エグゼクティブサマリー")]
    assert "論争はまだ始まっておらず" in head and "年122,090千円不足" in head
    _finish(DebateSession(run))
    md = report_markdown(run)
    head = md[md.index("## 要約"):md.index("## 1. エグゼクティブサマリー")]
    assert "第62期" in head and "「資金ショートの回避と持続的再建方針の策定」を目的として" in head
    assert "結論は「トリアージ宣告」である。" in head and "年122,090千円不足" in head
    assert "（一）雇用死守型の第二会社方式" in head and "経営者が決める" in head
