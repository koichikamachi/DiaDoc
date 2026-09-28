"""論争のステートマシン（LangGraph）。台本（モック）で動かし、本物の Gemini は呼ばない。

同梱の data/ を一時フォルダに複製して使い、チェックポイントは複製側の回次フォルダに書く。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.graph import DebateSession, formal_review
from core.interrupt import EmptyInterventionError, intervene
from core.runs import FrozenRunError, latest_run
from schema import DebateMessage, SourceRef

ROOT = Path(__file__).resolve().parents[1]
CRISIS, SAMPLE = "C002_sample_crisis", "C001_sample_alpha"


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def run_to_end(s: DebateSession, limit: int = 40) -> None:
    for _ in range(limit):
        if s.finished:
            return
        s.step()
    raise AssertionError("論争が終わらない")


def test_start_stops_before_the_first_speaker(data):
    s = DebateSession(latest_run(CRISIS))
    st = s.start()
    assert st.messages == [] and s.next_node == "radar" and not s.finished
    assert (latest_run(CRISIS).path / "checkpoints.sqlite").exists()


def test_one_step_is_one_speech(data):
    s = DebateSession(latest_run(CRISIS))
    new = s.step()
    assert [m.speaker for m in new] == ["radar"] and s.next_node == "growth"
    new = s.step()
    assert [m.speaker for m in new] == ["growth"] and s.next_node == "rebuild"


def test_crisis_scenario_reaches_triage_and_settles(data):
    s = DebateSession(latest_run(CRISIS))
    run_to_end(s)
    st = s.state()
    assert [(d.current, d.next, d.rule) for d in st.phase_history] == [
        ("exploration", "exploration", "continue"),
        ("exploration", "exploration", "levers_remaining"),   # 第2R：固定費と資産のレバーが未着手なので続ける
        ("exploration", "triage_ready", "gap_unmet"),         # 第3R：4レバーを試しても必要CFに届かない
        ("triage_ready", "settlement", "triage_declared"),
    ]
    assert st.monitor.levers_tried == ["売上・粗利", "原価・現場", "固定費・販管費", "資産売却・BS"]
    assert st.stop_reason == "トリアージ宣告" and st.triage_declared
    last = st.messages[-1]                                     # 宣告の後に、道の比較が1手入る
    assert last.speaker == "judge" and last.action == "比較" and len(last.comparison) == 3
    assert [a.in_time for a in last.comparison] == [True, True, False]  # 6・3・8か月 vs 残余6.8か月
    assert "選ぶかは人間" in last.text
    verdict = {r.message_id: r.verdict for r in st.rulings}
    poem = next(m for m in st.messages if m.speaker == "growth" and m.round == 1)
    assert verdict[poem.id] == "差し戻し"                          # 定性ポエムは差し戻し
    # 間に合うのは労務費・役員報酬の削減と在庫圧縮。値上げ（7か月後）と土地売却（8か月後）は数えない
    m = st.monitor
    assert m.accumulated_recovery_cf == 30_000 and m.one_time_cash == 4_000 and m.cash_runway_months == 6.8
    assert {c.bridge.account: c.in_time for c in m.counted} == {
        "sales": False, "lab": True, "sga_officer": True, "land": False, "rm": True}
    declaration = next(x for x in st.messages if x.action == "宣告")
    assert declaration.phase == "triage_ready" and "第二会社" in declaration.text and "詐害行為" in declaration.text
    # 探索段階の Rebuild はトリアージの語を使っていない
    assert all("第二会社" not in x.text for x in st.messages if x.speaker == "rebuild" and x.phase == "exploration")
    # トリアージ段階では Radar と Growth は話さない
    assert {x.speaker for x in st.messages if x.phase == "triage_ready"} == {"rebuild", "judge"}


def test_sample_company_settles_without_triage(data):
    s = DebateSession(latest_run(SAMPLE))
    run_to_end(s)
    st = s.state()
    assert all(d.next != "triage_ready" for d in st.phase_history)
    assert st.stop_reason == "膠着（資金不足なし）"
    assert not any(m.action == "宣告" for m in st.messages)


def test_run_round_stops_after_the_judge(data):
    s = DebateSession(latest_run(CRISIS))
    new = s.run_round()
    assert [m.speaker for m in new] == ["radar", "growth", "rebuild", "judge"]
    assert s.next_node == "radar" and s.state().round == 2
    s.run_round()
    assert s.state().phase == "exploration" and s.next_node == "radar"      # 第2R：未着手のレバーがあるので続く
    s.run_round()
    assert s.state().phase == "triage_ready" and s.next_node == "rebuild"   # フェーズが変わったところで止まる


def test_resume_from_checkpoint_in_a_new_session(data):
    run = latest_run(CRISIS)
    s1 = DebateSession(run)
    s1.step(), s1.step()
    s1.close()
    s2 = DebateSession(latest_run(CRISIS))                  # 画面の再描画・再起動の代わり
    assert s2.next_node == "rebuild" and len(s2.state().messages) == 2
    run_to_end(s2)
    assert s2.state().stop_reason == "トリアージ宣告"


def test_human_intervention_is_recorded_and_not_ruled(data):
    s = DebateSession(latest_run(CRISIS))
    s.step()
    msg = intervene(s, "雇用は全員維持することが前提です")
    assert s.next_node == "growth"                           # 介入しても次の発言者は変わらない
    st = s.state()
    assert st.messages[-1].id == msg.id and msg.speaker == "human"
    s.run_round()
    st = s.state()
    assert all(r.message_id != msg.id for r in st.rulings)   # 人間の言葉は審理しない
    assert st.monitor.stalemate_count == 0


def test_intervention_can_attach_a_material_that_becomes_citable(data):
    s = DebateSession(latest_run(CRISIS))
    intervene(s, "", attach_name="銀行面談メモ", attach_text="メインバンクは3か月の返済猶予に前向き。")
    assert "銀行面談メモ" in s.ctx.registry
    assert (latest_run(CRISIS).path / "inputs" / "銀行面談メモ.md").exists()
    with pytest.raises(EmptyInterventionError):
        intervene(s, "  ")


def test_frozen_run_cannot_be_advanced(data):
    from core.runs import start_next_run

    first = latest_run(CRISIS)
    start_next_run(CRISIS, "テスト")
    with pytest.raises(FrozenRunError):
        DebateSession(first).step()


def _m(**kw):
    base = dict(id="x", round=1, phase="exploration", speaker="rebuild", action="攻撃",
                text="資金効果が足りない", sources=[SourceRef(file="決算報告書第62期（架空）", page="3")],
                settle_condition="月次資金繰り表で確認")
    base.update(kw)
    return DebateMessage(**base)


def _state(data):
    s = DebateSession(latest_run(CRISIS))
    return s.start(), s.ctx.registry


def test_formal_review_rejects_sources_outside_the_registry(data):
    st, reg = _state(data)
    r = formal_review(_m(sources=[SourceRef(file="業界レポート2026", page="12")]), st, reg)
    assert r.verdict == "退け" and any("資料一覧にない" in x for x in r.reasons)


def test_rebuild_cannot_mention_triage_during_exploration(data):
    st, reg = _state(data)
    r = formal_review(_m(text="この会社は法的整理しかない"), st, reg)
    assert r.verdict == "差し戻し" and any("トリアージの語" in x for x in r.reasons)


def test_only_rebuild_in_triage_can_declare(data):
    st, reg = _state(data)
    assert formal_review(_m(action="宣告"), st, reg).verdict == "差し戻し"
    from schema import TriageOption

    opts = [TriageOption(name=n, keep=["事業"], discard=["法人格"], preconditions=["債権者の同意"]) for n in ("A", "B")]
    ok = _m(action="宣告", phase="triage_ready", text="Level 0 を宣告する", options=opts)
    assert formal_review(ok, st, reg).verdict == "通過"


def test_triage_declaration_carries_structured_options(data):
    s = DebateSession(latest_run(CRISIS))
    run_to_end(s)
    decl = next(m for m in s.state().messages if m.action == "宣告")
    assert len(decl.options) == 3
    assert all(o.name and o.keep and o.discard and o.preconditions for o in decl.options)
    assert any("詐害行為" in p for o in decl.options for p in o.preconditions)


def test_declaration_without_options_is_sent_back(data):
    from schema import TriageOption

    st, reg = _state(data)
    r = formal_review(_m(action="宣告", phase="triage_ready", text="Level 0 を宣告する"), st, reg)
    assert r.verdict == "差し戻し" and any("二つ以上" in x for x in r.reasons)
    opts = [TriageOption(name="A", keep=["事業"], discard=["法人格"], preconditions=["債権者の同意"]),
            TriageOption(name="B", keep=["雇用"], discard=["遊休地"], preconditions=[])]
    r = formal_review(_m(action="宣告", phase="triage_ready", text="Level 0", options=opts), st, reg)
    assert r.verdict == "差し戻し" and any("前提条件が書かれていない道" in x for x in r.reasons)


def test_addressed_intervention_lets_the_named_agent_answer_then_resumes(data):
    s = DebateSession(latest_run(CRISIS))
    s.step(), s.step()                                        # radar, growth
    assert s.next_node == "rebuild"
    intervene(s, "いきなり8%の削減は従業員の反発で難しいのでは？", addressee="growth")
    assert s.next_node == "growth" and s.state().reply_to == "growth"
    new = s.step()
    assert [m.speaker for m in new] == ["growth"]              # 指名された Growth が割り込んで答える
    assert s.next_node == "rebuild" and s.state().reply_to is None   # 元の順番に戻る
    s.step()
    assert s.next_node == "judge"


def test_unaddressed_intervention_goes_to_the_next_speaker(data):
    s = DebateSession(latest_run(CRISIS))
    s.step(), s.step()
    intervene(s, "雇用は全員維持が前提")
    assert s.next_node == "rebuild"


def test_pending_intervention_is_put_first_in_the_prompt(data):
    from agents.growth import Growth
    from agents.rebuild import Rebuild

    s = DebateSession(latest_run(CRISIS))
    s.step(), s.step()
    intervene(s, "いきなり8%の削減は難しいのでは？", addressee="growth")
    st = s.state()
    g = Growth().user_prompt(st, s.ctx)
    assert "【あなた宛て】いきなり8%の削減は難しいのでは？" in g and "まずこれに答える" in g
    assert "いきなり8%" not in Rebuild().user_prompt(st, s.ctx).split("# あなたへの指示")[0].split("これまでの発言")[0]


def test_comparison_can_be_added_to_a_debate_closed_before_it_existed(data):
    s = DebateSession(latest_run(CRISIS))
    run_to_end(s)
    assert not s.needs_comparison()                     # 今の手順では比較まで済んでいる
    # 比較の手順ができる前に閉じた論争（宣告の裁定で終わったもの）を、別のスレッドに再現する
    st = s.state()
    legacy = st.model_copy(update={"messages": [m for m in st.messages if m.action != "比較"]})
    s.config = {"configurable": {"thread_id": "legacy-test"}}
    s.app.update_state(s.config, legacy.model_dump(), as_node="judge")
    assert s.finished and s.needs_comparison()
    new = s.add_comparison()
    assert [m.action for m in new] == ["比較"] and s.finished and s.state().stop_reason == "トリアージ宣告"
