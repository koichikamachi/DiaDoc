"""発言を生成するもの。Gemini（本番）と台本（APIキーがないとき・テスト）の二つ。

どちらも出力は agents.base の型（AgentTurn／JudgeTurn）にそろえる。審査と判定はこの外側のプログラムが行うので、
台本で動かしても本番と同じ審査・監視指標・フェーズ判定を通る。
"""

from __future__ import annotations

import copy
import json
import logging
import time
from datetime import datetime

from pydantic import BaseModel

import config
from agents.base import AgentTurn, ComparisonTurn, JudgeTurn, monitor_values, preview_monitor


class _Blank(dict):
    def __missing__(self, key):
        return "{" + key + "}"


class ScriptedSpeaker:
    """会社ごとの台本（data/companies/<id>/debate_script.json）を順に読む。

    台本は「エージェント → フェーズ → 発言の並び」。同じフェーズで何番目の発言かで選び、尽きたら最後の発言を
    繰り返す（繰り返しは審判に差し戻され、膠着として数えられる）。文中の {runway} などには、その時点の
    監視指標（審理中の提案を仮に通した試算）が入る。
    """

    name = "mock"

    def generate(self, agent, system, user, schema: type[BaseModel], state, ctx) -> BaseModel:
        script = (ctx.script or {}).get(agent.id, {})
        if schema is ComparisonTurn:
            return ComparisonTurn.model_validate(script.get("comparison") or {"assessments": []})
        if schema is JudgeTurn:
            summaries = script.get("summaries", []) if isinstance(script, dict) else []
            i = state.round - 1
            return JudgeTurn(summary=summaries[i] if i < len(summaries) else "")
        entries = script.get(state.phase, [])
        if not entries:
            return AgentTurn(action="提示", text=f"（{agent.name} の台本がありません）")
        n = sum(1 for m in state.messages if m.speaker == agent.id and m.phase == state.phase)
        entry = copy.deepcopy(entries[min(n, len(entries) - 1)])
        values = _Blank(monitor_values(preview_monitor(state)))
        for k in ("text", "settle_condition"):
            if entry.get(k):
                entry[k] = entry[k].format_map(values)
        return AgentTurn.model_validate(entry)


class GeminiSpeaker:
    """Gemini の構造化出力で発言を生成する。失敗したら例外を上げ、論争の状態は進めない（再試行できる）。"""

    name = "gemini"
    RETRIES = 2   # 返答が壊れていたときに、裏で作り直させる回数
    # 返答の長さの上限。ふつうの発言は千トークン前後。生成が暴走して「6000…」と桁を延々と書き続けると、
    # 上限がなければ数万字・3分近く止まる（2026-10-01、乙精機ケース3で実例）。上限で打ち切れば十数秒で作り直しに移る
    MAX_OUTPUT_TOKENS = 4096

    def __init__(self, client=None, model: str | None = None, temperature: float = 0.4):
        if client is None:
            from google import genai

            logging.getLogger("google_genai._api_client").setLevel(logging.ERROR)
            client = genai.Client(api_key=config.gemini_api_key())
        self.client = client
        self.model = model or config.gemini_model()
        self.temperature = temperature

    def generate(self, agent, system, user, schema: type[BaseModel], state, ctx) -> BaseModel:
        """返答の JSON が壊れている・型に合わない（桁外れの数字など）ときは、画面にエラーを出す前に
        最大 RETRIES 回まで作り直させる。通信・認証などの失敗はやり直さずにそのまま上げる。"""
        last: Exception | None = None
        for attempt in range(1, self.RETRIES + 2):
            try:
                return self._once(agent, system, user, schema, state, ctx, attempt)
            except ValueError as e:   # pydantic の ValidationError・JSON の読み取り失敗はどちらも ValueError
                last = e
        raise last

    def _once(self, agent, system, user, schema, state, ctx, attempt: int) -> BaseModel:
        from google.genai import types

        t0 = time.time()
        record = {"at": datetime.now().isoformat(timespec="seconds"), "agent": agent.id, "round": state.round,
                  "phase": state.phase, "model": self.model, "schema": schema.__name__,
                  "prompt_chars": len(system) + len(user), "attempt": attempt}
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=self.temperature,
                    max_output_tokens=self.MAX_OUTPUT_TOKENS,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            record["raw"] = getattr(resp, "text", None)
            parsed = getattr(resp, "parsed", None)
            out = parsed if isinstance(parsed, schema) else schema.model_validate_json(resp.text)
            record["ok"] = True
            return out
        except Exception as e:
            record["ok"] = False
            record["error"] = f"{type(e).__name__}: {e}"[:2000]
            raise
        finally:
            record["seconds"] = round(time.time() - t0, 1)
            _trace(ctx, record)


def _trace(ctx, record: dict) -> None:
    """発言生成の記録を回次フォルダに追記する（APIキーは含まない）。記録に失敗しても論争は止めない。"""
    path = getattr(ctx, "trace_path", None)
    if path is None:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def default_speaker():
    return GeminiSpeaker() if config.debate_mode() == "gemini" else ScriptedSpeaker()
