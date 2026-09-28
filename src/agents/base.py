"""エージェントの基底。発言の出力型、論争の文脈（資料・数字・監視指標）、指示文の共通部分。

エージェントは「何を言うか」だけを担う。発言の審査、監視指標の計算、フェーズの判定はプログラム
（core.guardrails・core.metrics）が行い、エージェントはその結果を読むだけである。
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from core.guardrails import cash_sign
from core.metrics import cash_base, project
from schema import (
    Action,
    AgendaItem,
    AgentId,
    CashBase,
    CausalBridge,
    DebateMessage,
    Financials,
    Monitor,
    Phase,
    SourceRef,
    TriageOption,
    stamp,
)
from state import DebateState

# ---------------------------------------------------------------------------
# エージェントの出力型（Gemini の構造化出力にそのまま渡す）
# ---------------------------------------------------------------------------


class SourceOut(BaseModel):
    file: str = Field(description="引用できる資料の一覧にある資料名をそのまま書く")
    page: str = Field(description="頁（数字のみ）")


class AgendaOp(BaseModel):
    op: Literal["open", "close", "hold"] = Field(description="open=論点を開く、close=決着、hold=保留")
    id: str = Field(description="論点のID（A1, A2 など）")
    title: str = ""
    resolution: str = ""


class AgentTurn(BaseModel):
    action: Action
    text: str = Field(description="発言本文。日本語。金額は千円")
    agenda_id: str | None = None
    target_node: str | None = Field(default=None, description="意思決定ツリーのノード（任意）")
    sources: list[SourceOut] = Field(default_factory=list)
    settle_condition: str | None = Field(default=None, description="何が観察されれば決着するか")
    bridges: list[CausalBridge] = Field(default_factory=list)
    options: list[TriageOption] = Field(default_factory=list, description="トリアージ宣告のときだけ。三つの道")
    agenda_ops: list[AgendaOp] = Field(default_factory=list)


class AssessmentOut(BaseModel):
    name: str = Field(description="宣告された道の名前をそのまま書く")
    employment: str = Field(description="雇用はどうなるか（人数・条件）")
    cash: str = Field(description="当面の資金繰りをどう乗り切るか。何がいつまでに要るか")
    creditors: str = Field(description="金融機関・債権者に何を求めるか")
    months_needed: int = Field(description="道筋がつくまでの月数の見込み")
    risks: list[str] = Field(default_factory=list, description="主なリスク（2〜3件）")
    deciding_fact: str = Field(description="この道を選ぶか捨てるかの決め手になる観察事実")
    sources: list[SourceOut] = Field(default_factory=list)


class ComparisonTurn(BaseModel):
    assessments: list[AssessmentOut]
    summary: str = Field(default="", description="比較の要点（3文以内）。どの道を選ぶかは書かない")


class ContentReview(BaseModel):
    message_id: str
    verdict: Literal["通過", "差し戻し", "退け"]
    reason: str


class JudgeTurn(BaseModel):
    reviews: list[ContentReview] = Field(default_factory=list)
    summary: str = Field(default="", description="このラウンドの論点整理（3文以内）")
    agenda_ops: list[AgendaOp] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 論争の文脈
# ---------------------------------------------------------------------------
KEY_FIGURES = ("sales", "gp", "sga", "op", "div", "ord", "ni", "mat", "lab", "cash", "stl", "cltd", "ltd",
               "officer_loan", "ins_reserve", "suspense", "inv", "land", "ta", "tna")
MATERIAL_SUFFIXES = (".md", ".txt")
MATERIAL_LIMIT = 8000


@dataclass
class DebateContext:
    company: str
    display_name: str
    fictional: bool
    fin: Financials | None
    base: CashBase
    materials: dict[str, str] = field(default_factory=dict)   # 資料名 → 本文（ヒアリングメモなど）
    script: dict | None = None                                 # モック用の台本
    trace_path: Path | None = None                             # 発言生成の記録（Gemini の生の出力。調整用）
    mission: str | None = None                                 # 企業ごとの診断ミッションの初期値（meta.json）

    @property
    def registry(self) -> set[str]:
        """引用してよい資料名。ここにない資料名を出典にした主張は審理に使わない。"""
        docs = set(self.fin.documents) if self.fin else set()
        return docs | set(self.materials)

    @classmethod
    def from_run(cls, run) -> "DebateContext":
        from core.runs import company_dir

        meta = json.loads((company_dir(run.company) / "meta.json").read_text(encoding="utf-8"))
        fin = run.financials()
        base = cash_base(fin) if fin else CashBase(liquid_funds=None, simple_cf=None, debt_service=None,
                                                   free_cf=None, required_cf=None, basis=["財務データがありません"])
        materials: dict[str, str] = {}
        chain, r = [], run
        while r is not None:
            chain.append(r)
            r = r.parent()
        for r in reversed(chain):
            for p in r.inputs():
                if p.suffix.lower() in MATERIAL_SUFFIXES:
                    materials[p.stem] = p.read_text(encoding="utf-8")[:MATERIAL_LIMIT]
        script_path = company_dir(run.company) / "debate_script.json"
        script = json.loads(script_path.read_text(encoding="utf-8")) if script_path.exists() else None
        return cls(company=run.company, display_name=meta.get("display_name", run.company),
                   fictional=bool(meta.get("fictional")), fin=fin, base=base, materials=materials, script=script,
                   trace_path=run.path / "debate_trace.jsonl", mission=meta.get("mission"))

    def resolve_source(self, name: str | None) -> str | None:
        """出典の資料名を、引用できる資料の正式名に合わせる（空白・下線・全角半角・括弧の揺れだけを吸収する）。"""
        if not name:
            return name
        if name in self.registry:
            return name
        key = norm_name(name)
        hits = [r for r in self.registry if norm_name(r) == key]
        return hits[0] if len(hits) == 1 else name


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return "".join(ch for ch in s if not ch.isspace() and ch not in "_＿").replace("(", "（").replace(")", "）")


def to_sources(items: list[SourceOut]) -> list[SourceRef]:
    return [SourceRef(file=s.file.strip() or None, page=str(s.page).strip().lstrip("p.").strip() or None)
            for s in items]


def pending_bridges(state: DebateState) -> list[tuple[str, CausalBridge]]:
    """このラウンドでまだ審査されていない提案の因果ブリッジ（形式上の問題がないもの）。"""
    from core.guardrails import check_bridge

    ruled = {r.message_id for r in state.rulings}
    return [(m.id, b) for m in state.messages
            if m.round == state.round and m.id not in ruled and m.speaker in ("growth", "rebuild")
            for b in m.bridges if not check_bridge(b)]


def preview_monitor(state: DebateState) -> Monitor:
    """審理中の提案をすべて通したと仮定した試算。反論の材料に使う（判定には使わない）。"""
    m = state.monitor
    return project(m.base, state.passed_bridges() + pending_bridges(state), m.stalemate_count, m.rounds_completed)


def fmt_runway(m: float | None) -> str:
    return "資金流出なし" if m is None else f"約{m:.1f}か月"


def monitor_values(m: Monitor) -> dict[str, str]:
    """台本やテンプレートに差し込む値（千円・カンマ区切り）。"""
    def n(v):
        return "—" if v is None else f"{v:,}"
    return {"runway": fmt_runway(m.cash_runway_months), "base_runway": fmt_runway(m.base_runway_months),
            "required": n(m.base.required_cf), "acc": n(m.accumulated_recovery_cf), "gap": n(m.gap),
            "one_time": n(m.one_time_cash), "stalemate": str(m.stalemate_count)}


def _figures(ctx: DebateContext) -> list[str]:
    if ctx.fin is None:
        return ["（財務データなし）"]
    out = []
    for k in KEY_FIGURES:
        it = ctx.fin.items.get(k)
        if it is None or it.cur is None:
            continue
        prev = f"{it.prev:,} → " if it.prev is not None else ""
        out.append(f"- {k} {it.label}：{prev}{it.cur:,}（{it.source.file} p.{it.source.page}）")
    return out


def bridge_catalog() -> str:
    from tools.standard_accounts import ACCOUNTS

    return "、".join(f"{k}:{label}" for k, *_x, label, _t in ACCOUNTS if cash_sign(k, "減") is not None)


def _monitor_lines(m: Monitor, title: str) -> list[str]:
    v = monitor_values(m)
    lines = [f"## {title}",
             f"- 必要CF（年）：{v['required']}　回収CF累計（年、間に合うもののみ）：{v['acc']}　残りの不足：{v['gap']}",
             f"- 一回限りの資金：{v['one_time']}　残余月数：改善前 {v['base_runway']} → 改善後 {v['runway']}"]
    for c in m.counted:
        b = c.bridge
        lines.append(f"  - {c.message_id} {b.account} {b.direction} 資金効果 {b.cf_effect:,}（{b.lead_months}か月後、"
                     f"{'毎年' if b.recurring else '一回'}）：{'間に合う' if c.in_time else '資金が尽きた後なので数えない'}")
    return lines


def context_text(state: DebateState, ctx: DebateContext, recent: int = 14) -> str:
    """エージェントに渡す文脈。数字と判定はプログラムが出したものをそのまま示す。"""
    by_id: dict[str, list[str]] = {}
    for r in state.rulings:
        by_id.setdefault(r.message_id, []).append(f"{r.verdict}：{'／'.join(r.reasons)}")
    lines = [f"# 診断ミッション：{state.mission}",
             f"# 対象：{ctx.display_name}" + ("（架空モデル）" if ctx.fictional else ""),
             f"決算期：{ctx.fin.fiscal_period if ctx.fin else '—'}　単位：千円",
             f"現在：第{state.round}ラウンド、フェーズ {state.phase}", "",
             "## 主要な数字（出典）", *_figures(ctx), "",
             "## 資金の計算根拠（プログラムが計算。変えられない）", *[f"- {b}" for b in state.monitor.base.basis], "",
             *_monitor_lines(state.monitor, "資金の監視指標（通過した提案だけを反映）"), ""]
    if pending_bridges(state):
        lines += [*_monitor_lines(preview_monitor(state), "参考：審理中の提案をすべて通した場合の試算"), ""]
    from core.guardrails import LEVERS, levers_tried

    tried = levers_tried(state.messages, state.rulings)
    lines += ["## 改善レバーの消化状況（Growth が審査を通した提案。プログラムが集計）",
              "- 試した：" + ("・".join(tried) or "まだない"),
              "- 未着手：" + ("・".join(lv for lv in LEVERS if lv not in tried) or "なし（4つすべて試した）"), ""]
    lines += ["## 引用できる資料（出典の資料名はこの中から、頁付きで）", *[f"- {d}" for d in sorted(ctx.registry)], ""]
    for name, text in ctx.materials.items():
        lines += [f"## 資料本文：{name}", text, ""]
    if state.agenda:
        lines += ["## 論点アジェンダ", *[f"- {a.id} {a.title}［{a.status}］" for a in state.agenda], ""]
    if state.phase_history:
        d = state.phase_history[-1]
        lines += ["## 直近のフェーズ判定（プログラム）", f"- {d.current} → {d.next}：{d.reason}", ""]
    msgs = state.messages[-recent:]
    if msgs:
        lines.append("## これまでの発言（新しいものが下）")
        for m in msgs:
            src = "、".join(s.label() for s in m.sources) or "出典なし"
            lines.append(f"[{m.id}｜第{m.round}R｜{m.speaker}｜{m.action}] {m.text}（{src}）")
            if m.bridges:
                lines.append("   因果ブリッジ：" + "／".join(
                    f"{b.account}{b.direction} {b.amount:,}→資金{b.cf_effect:,}・{b.lead_months}か月" for b in m.bridges))
            for v in by_id.get(m.id, []):
                lines.append(f"   → 判定 {v}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 指示文の共通部分とエージェントの基底
# ---------------------------------------------------------------------------
COMMON_RULES = """あなたは経営診断の論争に参加する専門家の一人です。守るべき規律：
1. 数字は、文脈に示された資料・数字だけを使う。資料にない数字を作らない。金額は千円。
2. 主張には必ず出典（引用できる資料の一覧にある資料名と頁）を付ける。一覧にない資料名は審理に使われない。
3. 主張には「何が観察されれば決着するか」（決着条件）を具体的に書く。「なし」「不明」は差し戻される。
4. 相手に同意するだけの発言はしない。譲歩するときも、条件と数字を示す（馴れ合いの防止）。
5. 資金の監視指標とフェーズはプログラムが計算・判定する。あなたはそれを変えられないし、反論の材料として使ってよい。
6. 発言は日本語で、300字程度まで。"""


class Speaker(Protocol):
    """発言を生成するもの（Gemini または台本）。"""

    name: str

    def generate(self, agent: "Agent", system: str, user: str, schema: type[BaseModel], state: DebateState,
                 ctx: DebateContext) -> BaseModel: ...


class Agent:
    id: AgentId
    name: str
    role: str

    def system_prompt(self, phase: Phase, mission: str | None = None) -> str:
        head = f"【診断ミッション】: {mission}\nこのミッションが、4人に共通の討議目的である。発言はこの目的にどう資するかを意識する。\n\n" \
            if mission else ""
        return head + COMMON_RULES + "\n\n" + self.role_prompt(phase)

    def role_prompt(self, phase: Phase) -> str:
        raise NotImplementedError

    def task(self, state: DebateState, ctx: DebateContext) -> str:
        return "文脈を読み、あなたの役割に沿って次の発言を一つ出してください。"

    def pending_human(self, state: DebateState) -> list[DebateMessage]:
        """この担当者が最後に話した後に書き込まれた人間の介入。"""
        last = max((i for i, m in enumerate(state.messages) if m.speaker == self.id), default=-1)
        return [m for m in state.messages[last + 1:] if m.speaker == "human"
                and (m.addressee in (None, self.id))]

    def user_prompt(self, state: DebateState, ctx: DebateContext) -> str:
        head = ""
        pending = self.pending_human(state)
        if pending:
            lines = []
            for m in pending:
                to_me = m.addressee == self.id
                lines.append(f"- {'【あなた宛て】' if to_me else ''}{m.text}（{m.id}）")
            head = ("\n\n# 人間（ライム）からの介入：まずこれに答える\n" + "\n".join(lines) +
                    "\n人間の指摘・質問・条件には、発言の冒頭で直接答える。同意するなら条件と数字で、反論するなら根拠で答える。"
                    "指摘によって数字や時期が変わるなら、因果ブリッジも改める。あなたの段階の規律（使えない語など）は変わらない。")
        return context_text(state, ctx) + head + "\n\n# あなたへの指示\n" + self.task(state, ctx)

    def speak(self, state: DebateState, ctx: DebateContext, speaker: Speaker) -> AgentTurn:
        out = speaker.generate(self, self.system_prompt(state.phase, state.mission), self.user_prompt(state, ctx), AgentTurn,
                               state, ctx)
        return out if isinstance(out, AgentTurn) else AgentTurn.model_validate(out)


def normalize_bridge(b: CausalBridge) -> CausalBridge:
    """LLM の書き方の揺れだけを直す：科目名で書かれたキーを標準科目のキーに、負の変動額を正に。
    資金効果の符号や月数など、中身の判断に関わる値は変えない（変えれば審査を素通りさせることになる）。"""
    from tools.standard_accounts import KEYS, key_for_label

    account = b.account.strip()
    if account not in KEYS:
        account = key_for_label(account) or account
    return b.model_copy(update={"account": account, "amount": abs(b.amount)})


def to_message(turn: AgentTurn, state: DebateState, speaker: AgentId, ctx: DebateContext | None = None) -> DebateMessage:
    sources = to_sources(turn.sources)
    if ctx is not None:
        sources = [s.model_copy(update={"file": ctx.resolve_source(s.file)}) for s in sources]
    return DebateMessage(at=stamp(),
        id=f"R{state.round}-{speaker}-{len(state.messages) + 1}", round=state.round, phase=state.phase,
        speaker=speaker, action=turn.action, text=turn.text.strip(), agenda_id=turn.agenda_id,
        target_node=turn.target_node, sources=sources, settle_condition=turn.settle_condition,
        bridges=[normalize_bridge(b) for b in turn.bridges], options=turn.options,
    )


def apply_agenda_ops(agenda: list[AgendaItem], ops: list[AgendaOp], round_no: int) -> list[AgendaItem]:
    """論点の開閉。審理中が3件を超える開き方は、保留として登録する（黙って捨てない）。"""
    from core.guardrails import AgendaFullError, close_agenda, open_agenda

    for op in ops:
        if op.op == "open":
            if any(a.id == op.id for a in agenda):
                continue
            item = AgendaItem(id=op.id, title=op.title or op.id, opened_round=round_no)
            try:
                agenda = open_agenda(agenda, item)
            except AgendaFullError:
                agenda = agenda + [item.model_copy(update={"status": "保留", "resolution": "審理中の論点が3件あるため保留"})]
        elif any(a.id == op.id for a in agenda):
            agenda = close_agenda(agenda, op.id, "決着" if op.op == "close" else "保留", round_no, op.resolution)
    return agenda
