"""エージェントの指示文と、Gemini への渡し方（偽クライアントで確かめる。本物は呼ばない）。"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.base import AgentTurn, DebateContext, JudgeTurn, context_text
from agents.growth import Growth
from agents.moderator import Judge
from agents.rebuild import Rebuild
from agents.research import Radar
from agents.speakers import GeminiSpeaker, ScriptedSpeaker
from core.runs import latest_run
from state import initial_state

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return DebateContext.from_run(latest_run("C002_sample_crisis"))


def test_context_is_loaded_from_the_run(ctx):
    assert ctx.fictional and ctx.base.required_cf == 122_090
    assert "ヒアリングメモ_第62期（架空）" in ctx.registry and "決算報告書第62期（架空）" in ctx.registry
    text = context_text(initial_state("C002", "run_001_initial", ctx.base), ctx)
    assert "架空モデル" in text and "約5.0か月" in text and "短期借入金 180,000" in text


def test_growth_prompt_demands_causal_bridges():
    p = Growth().system_prompt("exploration")
    assert "因果ブリッジ" in p and "lead_months" in p and "限界利益" in p and "sga_salary:給料手当" in p
    assert "sga:" not in p.split("使える科目：")[1].split("\n")[0].replace("sga_", "")  # 合計行は使える科目に出さない


def test_rebuild_prompt_changes_with_phase():
    explore, triage = Rebuild().system_prompt("exploration"), Rebuild().system_prompt("triage_ready")
    assert "一切触れない" in explore and "宣告" not in explore.split("役割")[1].split("。")[0]
    assert all(w in triage for w in ("第二会社方式", "看板維持型", "法的整理", "詐害行為", "あなたは選ばない"))


def test_judge_cannot_change_the_phase():
    p = Judge().system_prompt("exploration")
    assert "フェーズの判定はプログラムが行う" in p and "通過に戻すことはできない" in p


def test_radar_opens_at_most_three_items():
    assert "最大3件" in Radar().system_prompt("exploration")


class FakeModels:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    def generate_content(self, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        return SimpleNamespace(parsed=None, text=self.payload)


def test_gemini_speaker_uses_structured_output(ctx):
    fake = FakeModels('{"action": "提案", "text": "残業を減らす", "sources": [{"file": "ヒアリングメモ_第62期（架空）", "page": "2"}],'
                      ' "settle_condition": "1か月後の残業時間", "bridges": [{"account": "lab", "direction": "減",'
                      ' "amount": 24000, "cf_effect": 24000, "lead_months": 1, "recurring": true}]}')
    sp = GeminiSpeaker(client=SimpleNamespace(models=fake), model="test-model")
    st = initial_state("C002", "run_001_initial", ctx.base)
    turn = Growth().speak(st, ctx, sp)
    assert isinstance(turn, AgentTurn) and turn.bridges[0].cf_effect == 24_000
    call = fake.calls[0]
    assert call.model == "test-model" and call.config.response_schema is AgentTurn
    assert "因果ブリッジ" in call.config.system_instruction and "ヒアリングメモ" in call.contents


def test_scripted_speaker_fills_live_numbers(ctx):
    st = initial_state("C002", "run_001_initial", ctx.base)
    turn = ScriptedSpeaker().generate(Radar(), "", "", AgentTurn, st, ctx)
    assert "約5.0か月" in turn.text and "{" not in turn.text
    assert isinstance(ScriptedSpeaker().generate(Judge(), "", "", JudgeTurn, st, ctx), JudgeTurn)


def test_llm_spelling_variants_are_normalized(ctx):
    from agents.base import to_message
    from schema import CausalBridge

    st = initial_state("C002", "run_001_initial", ctx.base)
    turn = AgentTurn(action="提案", text="残業を減らす",
                     sources=[{"file": "ヒアリングメモ 第62期(架空)", "page": "p.2"}],
                     bridges=[CausalBridge(account="労務費", direction="減", amount=-24000, cf_effect=24000,
                                           lead_months=1)])
    m = to_message(turn, st, "growth", ctx)
    assert m.sources[0].file == "ヒアリングメモ_第62期（架空）" and m.sources[0].page == "2"
    assert m.bridges[0].account == "lab" and m.bridges[0].amount == 24000 and m.bridges[0].cf_effect == 24000


def test_source_names_are_matched_only_when_unambiguous(ctx):
    assert ctx.resolve_source("決算報告書第62期 (架空)") == "決算報告書第62期（架空）"
    assert ctx.resolve_source("業界レポート") == "業界レポート"


def test_gemini_calls_are_traced_without_the_key(ctx, monkeypatch):
    import json as _json

    monkeypatch.setenv("GEMINI_API_KEY", "secret-key-should-not-appear")
    fake = FakeModels('{"action": "提示", "text": "事実", "sources": [{"file": "決算報告書第62期（架空）", "page": "3"}],'
                      ' "settle_condition": "試算表で確認"}')
    sp = GeminiSpeaker(client=SimpleNamespace(models=fake), model="test-model")
    Radar().speak(initial_state("C002", "run_001_initial", ctx.base), ctx, sp)
    lines = ctx.trace_path.read_text(encoding="utf-8").splitlines()
    rec = _json.loads(lines[-1])
    assert rec["agent"] == "radar" and rec["ok"] and rec["model"] == "test-model" and "事実" in rec["raw"]
    assert "secret-key" not in ctx.trace_path.read_text(encoding="utf-8")


def test_failed_gemini_call_is_traced_and_raised(ctx):
    class Boom:
        def generate_content(self, **kw):
            raise RuntimeError("quota exceeded")

    sp = GeminiSpeaker(client=SimpleNamespace(models=Boom()), model="m")
    with pytest.raises(RuntimeError):
        Radar().speak(initial_state("C002", "run_001_initial", ctx.base), ctx, sp)
    assert '"ok": false' in ctx.trace_path.read_text(encoding="utf-8")
