"""Phase 3 の土台：状態の型、資金の監視指標、因果ブリッジの形式審査、膠着の検知、フェーズ遷移の判定。

判定はすべて決定論。LLM は使わない。
"""

from __future__ import annotations

import json
import logging
import sqlite3

import pytest

from core import guardrails as g
from core.metrics import cash_base, project
from core.runs import latest_run
from schema import (
    AgendaItem,
    CashBase,
    CausalBridge,
    DebateMessage,
    Financials,
    LineItem,
    Ruling,
    SourceRef,
)
from state import ROUND_ORDER, DebateState, checkpoint_types, initial_state

SRC = [SourceRef(file="試算表", page="1")]


def fin_of(**vals: int) -> Financials:
    items = {k: LineItem(statement="x", section="x", label=k, cur=v, source=SourceRef(file="試算表", page="1"))
             for k, v in vals.items()}
    return Financials(company_id="T", fiscal_period="x", basis="単体", items=items)


# 資金ショート寸前の架空モデル：経常赤字、年間の約定返済 48,000、手元資金 60,000（千円）
CRISIS = dict(cash=60_000, ord=-20_000, ctx=300, e_dep=15_000, sga_dep=3_000, cltd=48_000)


def bridge(account="sga_salary", direction="減", amount=30_000, cf=30_000, lead=3, recurring=True):
    return CausalBridge(account=account, direction=direction, amount=amount, cf_effect=cf,
                        lead_months=lead, recurring=recurring)


# ---------------------------------------------------------------------------
# 資金の基礎値
# ---------------------------------------------------------------------------
def test_crisis_cash_base():
    b = cash_base(fin_of(**CRISIS))
    assert b.simple_cf == -20_000 - 300 + 18_000 == -2_300
    assert b.debt_service == 48_000
    assert b.free_cf == -50_300
    assert b.required_cf == 50_300
    assert any("設備投資は含めていない" in x for x in b.basis)


def test_sample_company_has_no_cash_gap():
    """アルファ製菓（第73期単体）は資金流出がなく、必要CFは0。トリアージの前提がない。"""
    fin = latest_run("C001_sample_alpha").financials()
    b = cash_base(fin)
    assert b.complete and b.free_cf > 0 and b.required_cf == 0
    m = project(b, [])
    assert m.cash_runway_months is None and m.gap == 0
    assert any("p.91" in x for x in b.basis)  # 現金預金の出典頁


def test_missing_cash_means_no_judgement():
    b = cash_base(fin_of(ord=1_000))
    assert not b.complete and b.required_cf is None and "cash" in b.missing
    assert project(b, []).gap is None


# ---------------------------------------------------------------------------
# 残余月数と回収CF（間に合うものだけ数える）
# ---------------------------------------------------------------------------
def test_base_runway():
    m = project(cash_base(fin_of(**CRISIS)), [])
    assert m.cash_runway_months == 14.3   # 60,000 ÷ (50,300 ÷ 12) ＝ 14.31… を小数1桁に切り捨て（保守側）
    assert m.accumulated_recovery_cf == 0 and m.gap == 50_300


def test_improvement_after_cash_runs_out_is_not_counted():
    m = project(cash_base(fin_of(**CRISIS)), [("m1", bridge(lead=20))])
    assert m.counted[0].in_time is False
    assert m.accumulated_recovery_cf == 0


def test_timely_improvement_extends_runway():
    base = cash_base(fin_of(**CRISIS))
    m = project(base, [("m1", bridge(lead=3))])
    assert m.counted[0].in_time and m.accumulated_recovery_cf == 30_000
    assert m.cash_runway_months > m.base_runway_months
    assert m.gap == 20_300


def test_one_time_cash_can_make_a_later_improvement_in_time():
    """資産売却の一時金で残余月数が延び、20か月後に効く改善が間に合うようになる。"""
    sale = bridge(account="inv", direction="減", amount=50_000, cf=50_000, lead=2, recurring=False)
    m = project(cash_base(fin_of(**CRISIS)), [("m1", bridge(lead=20)), ("m2", sale)])
    assert all(c.in_time for c in m.counted)
    assert m.one_time_cash == 50_000 and m.accumulated_recovery_cf == 30_000


def test_cash_consuming_effect_is_always_counted():
    cost = bridge(account="sga_adv", direction="増", amount=6_000, cf=-6_000, lead=40)
    m = project(cash_base(fin_of(**CRISIS)), [("m1", cost)])
    assert m.counted[0].in_time and m.accumulated_recovery_cf == -6_000
    assert m.gap == 56_300


def test_no_outflow_means_no_runway_limit():
    m = project(cash_base(fin_of(cash=10, ord=5_000, e_dep=100)), [])
    assert m.cash_runway_months is None and m.base.required_cf == 0


# ---------------------------------------------------------------------------
# 因果ブリッジの形式審査
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("b", [
    bridge(),                                                                  # 人件費の削減
    bridge(account="sales", direction="増", amount=100_000, cf=12_000, lead=6),  # 売上増（限界利益分だけ資金効果）
    bridge(account="land", direction="減", amount=80_000, cf=80_000, lead=4, recurring=False),  # 土地売却
    bridge(account="ltd", direction="増", amount=30_000, cf=30_000, lead=1, recurring=False),   # 借入
])
def test_valid_bridges(b):
    assert g.check_bridge(b) == []


@pytest.mark.parametrize("b,word", [
    (bridge(cf=-30_000), "符号が逆"),
    (bridge(account="sga"), "使えません"),          # 合計行
    (bridge(account="op"), "使えません"),           # 利益行
    (bridge(account="e_dep"), "使えません"),        # 資金の出入りを伴わない
    (bridge(account="nonexistent"), "使えません"),
    (bridge(amount=10_000, cf=30_000), "超えて"),
    (bridge(lead=-1), "所要月数"),
    (bridge(cf=0), "0です"),
])
def test_invalid_bridges(b, word):
    assert any(word in p for p in g.check_bridge(b))


def msg(mid="m1", speaker="growth", action="提案", text="販路を絞り込む", bridges=None, sources=SRC,
        settle="3か月後の粗利率", round_no=1):
    return DebateMessage(id=mid, round=round_no, phase="exploration", speaker=speaker, action=action, text=text,
                         sources=sources, settle_condition=settle, bridges=bridges or [])


def test_qualitative_poem_is_sent_back():
    r = g.review_debate_message(msg(text="現場の士気を高め、ブランドの物語を磨くべきだ"))
    assert r.verdict == "差し戻し" and any("因果ブリッジ" in x for x in r.reasons)


def test_proposal_with_bridge_passes():
    assert g.review_debate_message(msg(bridges=[bridge()])).verdict == "通過"


def test_bad_bridge_sends_back_and_missing_source_rejects():
    assert g.review_debate_message(msg(bridges=[bridge(cf=-1)])).verdict == "差し戻し"
    assert g.review_debate_message(msg(bridges=[bridge()], sources=[])).verdict == "退け"


def test_attack_needs_no_bridge():
    assert g.review_debate_message(msg(speaker="rebuild", action="攻撃")).verdict == "通過"


# ---------------------------------------------------------------------------
# 膠着と論点アジェンダ
# ---------------------------------------------------------------------------
def test_stalemate_counts_rounds_without_fresh_passed_claims():
    m1, m2 = msg("m1", text="A案"), msg("m2", text="A案。", round_no=2)
    r1, r2 = Ruling(message_id="m1", round=1, verdict="通過"), Ruling(message_id="m2", round=2, verdict="通過")
    assert g.update_stalemate(0, 1, [m1], [r1]) == 0                  # 新しく通過
    assert g.update_stalemate(0, 2, [m1, m2], [r1, r2]) == 1          # 同じ主張の繰り返し
    r3 = Ruling(message_id="m3", round=2, verdict="差し戻し")
    assert g.update_stalemate(1, 2, [m1, msg("m3", round_no=2)], [r1, r3]) == 2  # 通過なし


def test_radar_facts_do_not_break_stalemate():
    r = msg("r1", speaker="radar", action="提示", text="事実の提示")
    assert g.update_stalemate(1, 1, [r], [Ruling(message_id="r1", round=1, verdict="通過")]) == 2


def test_triage_without_valid_declaration_is_capped():
    d = g.decide_phase("triage_ready", mon(rounds=6))
    assert d.next == "settlement" and d.stop_reason == "宣告不成立（上限到達）"


def test_asset_sale_may_bring_more_cash_than_book_value():
    assert g.check_bridge(bridge(account="land", direction="減", amount=38_000, cf=55_000, lead=8, recurring=False)) == []


def test_short_term_borrowing_is_optional_in_reconciliation():
    from core.guardrails import reconcile

    fin = latest_run("C001_sample_alpha").financials()
    assert "stl" not in fin.items
    tcl = next(c for c in reconcile(fin).checks if c.name == "流動負債合計")
    assert tcl.status == "一致" and "stl" not in tcl.missing


def test_crisis_model_reconciles_fully_and_runs_out_of_cash():
    from core.guardrails import reconcile

    fin = latest_run("C002_sample_crisis").financials()
    rep = reconcile(fin)
    assert rep.total == 38 and rep.count("一致") == 38 and rep.rounding_diffs == 0
    b = cash_base(fin)
    assert b.required_cf == 122_090 and any("短期借入金 180,000" in x for x in b.basis)
    assert project(b, []).cash_runway_months == pytest.approx(5.01, abs=0.01)


def test_no_unrealized_gain_means_real_bs_equals_nominal():
    from core.metrics import balance_sheet

    fin = latest_run("C002_sample_crisis").financials()
    assert balance_sheet(fin, "real")["純資産"] == balance_sheet(fin, "nominal")["純資産"] == 44_710


def test_human_intervention_does_not_break_stalemate():
    h = msg("h1", speaker="human", action="介入", text="銀行は返済猶予に応じない見込み")
    assert g.update_stalemate(1, 1, [h], [Ruling(message_id="h1", round=1, verdict="通過")]) == 2


def agenda(i, status="審理中"):
    return AgendaItem(id=f"A{i}", title=f"論点{i}", status=status, opened_round=1)


def test_agenda_is_capped_at_three():
    items = []
    for i in range(3):
        items = g.open_agenda(items, agenda(i))
    with pytest.raises(g.AgendaFullError):
        g.open_agenda(items, agenda(9))
    items = g.close_agenda(items, "A0", "決着", 2, "解決")
    assert len(g.open_agenda(items, agenda(9))) == 4


def test_state_rejects_more_than_three_open_items():
    base = cash_base(fin_of(**CRISIS))
    with pytest.raises(ValueError):
        DebateState(company_id="T", run_id="r", monitor=project(base, []), agenda=[agenda(i) for i in range(4)])


# ---------------------------------------------------------------------------
# フェーズ遷移
# ---------------------------------------------------------------------------
def mon(fin_vals=CRISIS, passed=(), stalemate=0, rounds=1, levers=g.LEVERS):
    """levers：Growth が試した改善レバー（既定は4つすべて。トリアージの前提を満たした状態）。"""
    m = project(cash_base(fin_of(**fin_vals)), list(passed), stalemate, rounds)
    return m.model_copy(update={"levers_tried": list(levers)})


HEALTHY = dict(cash=1_700_000, ord=2_600_000, ctx=820_000, e_dep=1_560_000, cltd=4_400)


def test_gap_unmet_after_two_rounds_goes_to_triage():
    assert g.decide_phase("exploration", mon(rounds=1)).next == "exploration"
    d = g.decide_phase("exploration", mon(passed=[("m1", bridge())], rounds=2))
    assert d.next == "triage_ready" and d.rule == "gap_unmet" and "20,300" in d.reason


def test_stalemate_with_gap_goes_to_triage():
    d = g.decide_phase("exploration", mon(stalemate=2, rounds=1), policy=g.PhasePolicy(gap_check_round=3))
    assert d.next == "triage_ready" and d.rule == "stalemate_with_gap"


# --- 2026-09-28 あがきの規律：4つの改善レバーを試すまでトリアージに進まない -----------------------
def test_untried_levers_keep_the_exploration_going():
    d = g.decide_phase("exploration", mon(passed=[("m1", bridge())], rounds=2, levers=("原価・現場",)))
    assert d.next == "exploration" and d.rule == "levers_remaining"
    assert "売上・粗利・固定費・販管費・資産売却・BS" in d.reason


def test_stalemate_does_not_trigger_triage_while_levers_remain():
    d = g.decide_phase("exploration", mon(stalemate=2, rounds=2, levers=("売上・粗利",)))
    assert d.next == "exploration" and d.rule == "levers_remaining"


def test_round_limit_triggers_triage_even_with_untried_levers():
    d = g.decide_phase("exploration", mon(rounds=4, levers=("売上・粗利",)))
    assert d.next == "triage_ready" and d.rule == "gap_unmet_at_limit" and "未着手のレバー" in d.reason


def test_lever_rule_can_be_switched_off():
    d = g.decide_phase("exploration", mon(rounds=2, levers=()), policy=g.PhasePolicy(require_all_levers=False))
    assert d.next == "triage_ready" and d.rule == "gap_unmet"


@pytest.mark.parametrize("account,lever", [
    ("sales", "売上・粗利"), ("lab", "原価・現場"), ("mat", "原価・現場"), ("e_pow", "原価・現場"),
    ("sga_officer", "固定費・販管費"), ("sga_adv", "固定費・販管費"), ("ie", "固定費・販管費"),
    ("land", "資産売却・BS"), ("rm", "資産売却・BS"), ("ar", "資産売却・BS"), ("ins_reserve", "資産売却・BS"),
])
def test_lever_of_account(account, lever):
    assert g.lever_of(account) == lever


def test_levers_tried_counts_only_passed_growth_proposals():
    m1 = msg("g1", bridges=[bridge(account="sales", direction="増", amount=10, cf=5)])
    m2 = msg("g2", bridges=[bridge(account="land", direction="減", amount=10, cf=10, recurring=False)])
    m3 = msg("r1", speaker="rebuild", bridges=[bridge(account="sga_officer")])
    rulings = [Ruling(message_id="g1", round=1, verdict="通過"), Ruling(message_id="g2", round=1, verdict="差し戻し"),
               Ruling(message_id="r1", round=1, verdict="通過")]
    assert g.levers_tried([m1, m2, m3], rulings) == ["売上・粗利"]


def test_gap_closed_goes_to_settlement_without_triage():
    d = g.decide_phase("exploration", mon(passed=[("m1", bridge(amount=60_000, cf=60_000))], rounds=1))
    assert d.next == "settlement" and d.stop_reason == "改善策で充足"


@pytest.mark.parametrize("stalemate,rounds,stop", [(2, 2, "膠着（資金不足なし）"), (0, 4, "上限到達")])
def test_healthy_company_never_goes_to_triage(stalemate, rounds, stop):
    d = g.decide_phase("exploration", mon(HEALTHY, stalemate=stalemate, rounds=rounds))
    assert d.next == "settlement" and d.stop_reason == stop


def test_missing_cash_data_never_triggers_triage():
    d = g.decide_phase("exploration", mon(dict(ord=-5_000), stalemate=2, rounds=2))
    assert d.next == "settlement" and d.stop_reason == "膠着（資金データ不足）"


def test_triage_ready_waits_for_declaration_then_settles():
    m = mon(rounds=2)
    assert g.decide_phase("triage_ready", m).next == "triage_ready"
    d = g.decide_phase("triage_ready", m, triage_declared=True)
    assert d.next == "settlement" and d.stop_reason == "トリアージ宣告"
    assert g.decide_phase("settlement", m).next == "settlement"


# ---------------------------------------------------------------------------
# 状態の型とチェックポイント
# ---------------------------------------------------------------------------
def test_initial_state_and_passed_bridges_follow_latest_ruling():
    s = initial_state("T", "run_001", cash_base(fin_of(**CRISIS)))
    assert s.phase == "exploration" and s.next_speaker == ROUND_ORDER[0] == "radar"
    s = s.model_copy(update={
        "messages": [msg("m1", bridges=[bridge()]), msg("m2", bridges=[bridge(lead=5)])],
        "rulings": [Ruling(message_id="m1", round=1, verdict="差し戻し"),
                    Ruling(message_id="m1", round=1, verdict="通過"),
                    Ruling(message_id="m2", round=1, verdict="退け")],
    })
    assert [mid for mid, _ in s.passed_bridges()] == ["m1"]


def test_state_survives_sqlite_checkpoint_without_unregistered_types(tmp_path, caplog):
    """画面の再描画やアプリの再起動をまたいで、途中の議論を型のまま復元できる。"""
    import operator  # noqa: F401
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, START, StateGraph

    def speak(s: DebateState):
        m = msg(f"m{len(s.messages) + 1}", bridges=[bridge()])
        return {"messages": [m], "rulings": [Ruling(message_id=m.id, round=s.round, verdict="通過")]}

    def judge(s: DebateState):
        monitor = project(s.monitor.base, s.passed_bridges(), rounds_completed=1)
        return {"monitor": monitor, "phase_history": [g.decide_phase(s.phase, monitor)]}

    gr = StateGraph(DebateState)
    gr.add_node("growth", speak)
    gr.add_node("judge", judge)
    gr.add_edge(START, "growth")
    gr.add_edge("growth", "judge")
    gr.add_edge("judge", END)
    db = tmp_path / "checkpoints.sqlite"

    def compiled():
        conn = sqlite3.connect(db, check_same_thread=False)
        saver = SqliteSaver(conn, serde=JsonPlusSerializer(allowed_msgpack_modules=checkpoint_types()))
        return gr.compile(checkpointer=saver, interrupt_before=["growth", "judge"])

    cfg = {"configurable": {"thread_id": "C002/run_001"}}
    caplog.set_level(logging.WARNING)
    app = compiled()
    app.invoke(initial_state("C002", "run_001", cash_base(fin_of(**CRISIS))), cfg)
    app.invoke(None, cfg)                   # growth が1手話して judge の前で止まる
    assert app.get_state(cfg).next == ("judge",)

    app2 = compiled()                       # 別の接続（再起動の代わり）から続きを実行
    app2.invoke(None, cfg)
    v = app2.get_state(cfg).values
    assert isinstance(v["monitor"].counted[0].bridge, CausalBridge)
    assert v["monitor"].accumulated_recovery_cf == 30_000
    assert v["phase_history"][0].next == "exploration"
    assert "unregistered" not in caplog.text
