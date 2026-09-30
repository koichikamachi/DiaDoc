"""改善パッケージ（2026-09-30）：反論による差し戻し・減額採択、閉じた論争の再開、残余月数の上限、画面の細部。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.challenge import challenge_rulings
from core.graph import DebateSession
from core.interrupt import intervene
from core.metrics import _runway, project, runway_label
from core.runs import latest_run
from schema import CashBase, CausalBridge, DebateMessage, Ruling, SourceRef

ROOT = Path(__file__).resolve().parents[1]
CRISIS, SAMPLE = "C002_sample_crisis", "C001_sample_alpha"
SRC = [SourceRef(file="決算報告書", page="3")]


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


# ---------------------------------------------------------------------------
# 反論による差し戻し・減額採択
# ---------------------------------------------------------------------------
def _proposal():
    return DebateMessage(id="R1-growth-2", round=1, phase="exploration", speaker="growth", action="提案",
                         text="労務費の削減と役員報酬の減額", sources=SRC, settle_condition="人員計画",
                         bridges=[CausalBridge(account="lab", direction="減", amount=20_000, cf_effect=20_000, lead_months=3),
                                  CausalBridge(account="sga_officer", direction="減", amount=5_000, cf_effect=5_000,
                                               lead_months=1)])


def _attack(feasible, account="lab", mid="R1-rebuild-3"):
    return DebateMessage(id=mid, round=1, phase="exploration", speaker="rebuild", action="攻撃",
                         text="労務費2割減は現場が回らない", sources=SRC, settle_condition="工数表",
                         target_message="R1-growth-2", challenged_account=account, feasible_cf=feasible)


def _passed(*ids, rnd=1):
    return [Ruling(message_id=i, round=rnd, verdict="通過") for i in ids]


def test_attack_with_a_realistic_amount_reduces_the_proposal():
    msgs = [_proposal(), _attack(6_000)]
    out = challenge_rulings(msgs, _passed("R1-growth-2", "R1-rebuild-3"), 1)
    assert len(out) == 1 and out[0].verdict == "通過" and out[0].reduced and out[0].by == "challenge"
    lab, officer = out[0].adjusted_bridges
    assert (lab.cf_effect, lab.amount) == (6_000, 6_000) and officer.cf_effect == 5_000   # 疑義のない科目はそのまま
    assert out[0].reasons[0].startswith("減額採択")


def test_attack_that_sees_no_effect_sends_the_proposal_back():
    out = challenge_rulings([_proposal(), _attack(0)], _passed("R1-growth-2", "R1-rebuild-3"), 1)
    assert out[0].verdict == "差し戻し" and out[0].adjusted_bridges is None


def test_attack_that_failed_review_changes_nothing():
    rulings = _passed("R1-growth-2") + [Ruling(message_id="R1-rebuild-3", round=1, verdict="差し戻し")]
    assert challenge_rulings([_proposal(), _attack(0)], rulings, 1) == []


def test_attack_on_the_whole_proposal_scales_every_positive_bridge():
    out = challenge_rulings([_proposal(), _attack(10_000, account=None)], _passed("R1-growth-2", "R1-rebuild-3"), 1)
    assert [b.cf_effect for b in out[0].adjusted_bridges] == [8_000, 2_000]            # 25,000 → 10,000 を按分


def test_a_passed_defence_restores_the_proposal():
    msgs = [_proposal(), _attack(6_000)]
    rulings = _passed("R1-growth-2", "R1-rebuild-3")
    rulings += challenge_rulings(msgs, rulings, 1)
    defence = DebateMessage(id="R2-growth-6", round=2, phase="exploration", speaker="growth", action="防御",
                            text="工数表では2割減でも回る", sources=SRC, settle_condition="工数表の確認",
                            target_message="R1-rebuild-3")
    msgs.append(defence)
    rulings += _passed("R2-growth-6", rnd=2)
    back = challenge_rulings(msgs, rulings, 2)
    assert len(back) == 1 and back[0].verdict == "通過" and back[0].adjusted_bridges is None
    assert challenge_rulings(msgs, rulings + back, 2) == []                           # 変わらなければ積まない


def test_reduced_amount_is_what_the_monitor_counts():
    from state import DebateState

    msgs = [_proposal(), _attack(6_000)]
    rulings = _passed("R1-growth-2", "R1-rebuild-3")
    rulings += challenge_rulings(msgs, rulings, 1)
    base = CashBase(liquid_funds=50_000, simple_cf=0, debt_service=40_000, free_cf=-40_000, required_cf=40_000)
    st = DebateState(company_id="C", run_id="r", monitor=project(base, []), messages=msgs, rulings=rulings)
    assert sorted(b.cf_effect for _, b in st.passed_bridges()) == [5_000, 6_000]


def test_attack_in_the_scripted_debate_reduces_growths_proposal(data):
    """台本の第2ラウンドで、Rebuild の攻撃に対象と現実的な額を持たせると、Growth の提案は減額採択になる。"""
    s = DebateSession(latest_run(CRISIS))
    s.run_round()                                                                      # 第1ラウンド
    s.step()                                                                           # radar
    s.step()                                                                           # growth（売上と労務費の提案）
    growth = s.state().messages[-1]
    first = growth.bridges[0]
    s.ctx.script["rebuild"]["exploration"][1].update(
        target_message=growth.id, challenged_account=first.account, feasible_cf=first.cf_effect // 2)
    s.run_round()
    st = s.state()
    attack = [m for m in st.messages if m.speaker == "rebuild"][-1]
    assert attack.target_message == growth.id
    assert [r for r in st.rulings if r.message_id == attack.id][-1].verdict == "通過"
    last = [r for r in st.rulings if r.message_id == growth.id][-1]
    assert last.reduced and last.adjusted_bridges[0].cf_effect == first.cf_effect // 2
    assert any("減額採択" in x for x in st.messages[-1].judge_note.sent_back)
    counted = {c.bridge.account: c.bridge.cf_effect for c in st.monitor.counted if c.message_id == growth.id}
    assert counted[first.account] == first.cf_effect // 2                              # 監視指標も減らした額で数える


# ---------------------------------------------------------------------------
# 閉じた論争の再開
# ---------------------------------------------------------------------------
def _run_to_end(s):
    for _ in range(40):
        if s.finished:
            return
        s.step()
    raise AssertionError("論争が終わらない")


def test_intervention_after_closing_reopens_the_exploration(data):
    s = DebateSession(latest_run(CRISIS))
    _run_to_end(s)
    before = s.state()
    intervene(s, "メインバンクが追加融資に前向きになった。前提を見直してほしい")
    st = s.state()
    assert not s.finished and st.phase == "exploration" and st.stop_reason is None and not st.triage_declared
    assert st.round == before.round + 1 and st.reopen_base == before.round and st.reopened == 1
    assert st.phase_history[-1].rule == "reopened" and st.phase_history[-1].current == "settlement"
    assert st.messages[-1].speaker == "human" and "再開" in st.messages[-2].text   # 再開の記録の後に介入が続く
    assert len(st.messages) > len(before.messages)                                  # 履歴は消さない
    new = s.step()
    assert new and new[0].speaker == "radar"


def test_mission_change_after_closing_reopens(data):
    s = DebateSession(latest_run(CRISIS))
    _run_to_end(s)
    s.set_mission("スポンサー・提携先の選定条件の整理")
    st = s.state()
    assert st.phase == "exploration" and st.mission == "スポンサー・提携先の選定条件の整理" and st.reopened == 1


def test_round_limit_counts_from_the_reopening(data):
    s = DebateSession(latest_run(CRISIS))
    _run_to_end(s)
    intervene(s, "条件が変わった")
    s.run_round()
    d = s.state().phase_history[-1]
    assert d.rule != "max_rounds"                                                  # 再開直後に上限で閉じない


def test_open_debate_cannot_be_reopened(data):
    s = DebateSession(latest_run(CRISIS))
    s.step()
    with pytest.raises(ValueError):
        s.reopen("試し")


# ---------------------------------------------------------------------------
# 残余月数の上限
# ---------------------------------------------------------------------------
def test_tiny_outflow_is_capped_as_risk_resolved():
    assert _runway(1_000_000, -10, []) is None                                     # 以前は約1.2万か月と出ていた
    assert _runway(100_000, -12_000, []) == pytest.approx(100.0)
    assert runway_label(None, -10) == "資金ショートリスク解消（10年超）"
    assert runway_label(None, 5_000) == "資金流出なし"
    assert runway_label(20.34, -1) == "約20.3か月" and runway_label(20.34, -1, short=True) == "20.3か月"


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------
def _app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "src/ui/app.py"), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_intervention_has_no_checkbox_and_always_answers(data):
    at = _app()
    assert not [c for c in at.checkbox if "すぐ1手" in (c.label or "")]
    at.text_area(key="intervene_text").input("雇用は維持が前提です")
    at.button(key="FormSubmitter:intervene-介入する").click().run()
    st_ = DebateSession(latest_run(SAMPLE)).state()
    assert [m.speaker for m in st_.messages][:2] == ["human", "radar"]


def test_free_text_mission_field_only_for_free_choice(data):
    at = _app()
    assert not [t for t in at.text_input if t.key == "mission_free"]
    at.selectbox(key="mission_choice").set_value("（自由に書く）").run()
    assert [t for t in at.text_input if t.key == "mission_free"]


def test_radar_is_told_to_point_out_rather_than_open():
    from agents.research import Radar

    prompt = Radar().role_prompt("exploration")
    assert "論点があることを指摘します" in prompt and "注意を向けるべきです" in prompt


# ---------------------------------------------------------------------------
# 生成の失敗への備え（桁外れの数字・壊れた JSON）
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, text):
        self.text, self.parsed = text, None


class _Client:
    def __init__(self, texts):
        self.texts, self.calls = list(texts), 0
        self.models = self

    def generate_content(self, **kw):
        self.calls += 1
        return _Resp(self.texts.pop(0))


class _Agent:
    id = "rebuild"


class _State:
    round, phase = 1, "exploration"


class _Ctx:
    trace_path = None


RUNAWAY = '{"action": "攻撃", "text": "過大", "feasible_cf": 1' + "0" * 40 + "}"
GOOD = '{"action": "攻撃", "text": "労務費2割減は無理", "feasible_cf": 6000}'


def _speaker(texts):
    from agents.speakers import GeminiSpeaker

    return GeminiSpeaker(client=_Client(texts), model="fake")


def test_runaway_number_is_regenerated_behind_the_scenes():
    from agents.base import AgentTurn

    sp = _speaker([RUNAWAY, GOOD])
    out = sp.generate(_Agent(), "sys", "user", AgentTurn, _State(), _Ctx())
    assert out.feasible_cf == 6000 and sp.client.calls == 2


def test_gives_up_after_the_retries_and_the_state_can_be_retried():
    from agents.base import AgentTurn

    sp = _speaker([RUNAWAY] * 3)
    with pytest.raises(ValueError):
        sp.generate(_Agent(), "sys", "user", AgentTurn, _State(), _Ctx())
    assert sp.client.calls == 3                                                     # 1回＋作り直し2回


def test_absurd_amounts_are_rejected():
    from pydantic import ValidationError

    from agents.base import AgentTurn

    with pytest.raises(ValidationError):
        AgentTurn.model_validate_json('{"action": "攻撃", "text": "x", "feasible_cf": 1000000000}')
    with pytest.raises(ValidationError):
        CausalBridge(account="lab", direction="減", amount=5, cf_effect=10**12, lead_months=1)
    assert CausalBridge(account="lab", direction="減", amount=999_999_999, cf_effect=-5, lead_months=1)


def test_error_message_names_the_button():
    src = (ROOT / "src/ui/components/timeline.py").read_text(encoding="utf-8")
    assert "もう一度「▶ 1手進める」を押すと" in src
