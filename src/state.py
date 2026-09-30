"""LangGraph の共有ステート（DebateState）。

発言（messages）と判定（rulings）は「積み上げ」で、書き換えない。監視指標は通過した因果ブリッジから
毎回計算し直す（core.metrics.project）。フェーズの遷移は core.guardrails.decide_phase が決め、
Judge はそれを宣言・説明するだけである。
"""

from __future__ import annotations

import operator
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

import schema
from core.guardrails import MAX_OPEN_AGENDA
from schema import (
    AgendaItem,
    AgentId,
    CashBase,
    CausalBridge,
    DebateMessage,
    Monitor,
    Phase,
    PhaseDecision,
    Ruling,
)

DEFAULT_MISSION = "資金ショートの回避と持続的再建方針の策定"

# 1ラウンドの発言順：事実と論点 → 改善案 → 資金の検証 → 審査とフェーズ判定
ROUND_ORDER: tuple[AgentId, ...] = ("radar", "growth", "rebuild", "judge")


class DebateState(BaseModel):
    company_id: str
    run_id: str
    mission: str = DEFAULT_MISSION      # 診断ミッション（主訴）。全員が共通の討議目的として意識する
    messages: Annotated[list[DebateMessage], operator.add] = Field(default_factory=list)
    rulings: Annotated[list[Ruling], operator.add] = Field(default_factory=list)
    phase: Phase = "exploration"
    phase_history: Annotated[list[PhaseDecision], operator.add] = Field(default_factory=list)
    monitor: Monitor
    agenda: list[AgendaItem] = Field(default_factory=list)
    round: int = 1
    next_speaker: AgentId | None = "radar"   # None は論争の終了
    triage_declared: bool = False
    reply_to: AgentId | None = None      # 人間に指名され、順番を割り込んで答える担当者
    resume_to: AgentId | None = None     # 指名された担当者が答えた後に戻る発言者
    adopted_option: str | None = None    # 人間が採った道（論争の後に記録する。論争の審査・判定には使わない）
    adopted_note: str = ""
    stop_reason: str | None = None
    reopen_base: int = 0                 # 論争を再開したときのラウンド。ラウンドの上限は再開からの数で見る
    reopened: int = 0                    # 再開した回数

    @model_validator(mode="after")
    def _agenda_cap(self) -> "DebateState":
        if sum(1 for a in self.agenda if a.status == "審理中") > MAX_OPEN_AGENDA:
            raise ValueError(f"審理中の論点は{MAX_OPEN_AGENDA}件までです")
        return self

    @property
    def finished(self) -> bool:
        return self.phase == "settlement" and self.stop_reason is not None

    def passed_bridges(self) -> list[tuple[str, CausalBridge]]:
        """Judge が通過させた発言の因果ブリッジ（発言ID付き）。後の判定が優先する。"""
        latest: dict[str, Ruling] = {}
        for r in self.rulings:
            latest[r.message_id] = r
        out = []
        for m in self.messages:
            r = latest.get(m.id)
            if r is not None and r.verdict == "通過":   # 減額採択なら、反論を受けて減らした資金効果で数える
                out += [(m.id, b) for b in (r.adjusted_bridges if r.adjusted_bridges is not None else m.bridges)]
        return out


def initial_state(company_id: str, run_id: str, base: CashBase, mission: str | None = None) -> DebateState:
    from core.metrics import project

    return DebateState(company_id=company_id, run_id=run_id, monitor=project(base, []),
                       mission=(mission or "").strip() or DEFAULT_MISSION)


def checkpoint_types() -> list[tuple[str, str]]:
    """チェックポイント（SQLite）から復元してよい型の一覧。LangGraph の serde に登録する。"""
    names = [n for n, obj in vars(schema).items() if isinstance(obj, type) and issubclass(obj, BaseModel)
             and obj.__module__ == schema.__name__]
    return [(schema.__name__, n) for n in names] + [(__name__, "DebateState")]
