"""データ構造の定義（Pydantic v2）。

財務データ、出典、主張と形式審査の判定、検算結果、分析回次のメタ情報を扱う。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 出典
# ---------------------------------------------------------------------------
class SourceRef(BaseModel):
    """出典。ファイル（書類）と、その中の位置（頁など）の組。"""

    file: str | None = None
    page: str | None = None

    def is_complete(self) -> bool:
        return bool((self.file or "").strip()) and bool((self.page or "").strip())

    def label(self) -> str:
        return f"{self.file or '（書類不明）'} p.{self.page or '？'}"


# ---------------------------------------------------------------------------
# 財務データ
# ---------------------------------------------------------------------------
Rounding = Literal["truncate_thousand", "round_thousand", "yen"]


class Component(BaseModel):
    """区分ごとに開示された値（例：販売費の給料手当、一般管理費の給料手当）。"""

    section: str
    source_label: str = ""
    prev: int | None = None
    cur: int | None = None
    page: str | None = None


class LineItem(BaseModel):
    statement: str
    section: str
    label: str
    source_label: str = ""
    prev: int | None = None
    cur: int | None = None
    mapping: str = ""
    is_total: bool = False
    source: SourceRef = Field(default_factory=SourceRef)
    note: str = ""
    breakdown: list[Component] = Field(default_factory=list)  # 区分ごとの値（合計を算出したときの根拠）


class SupplementaryItem(BaseModel):
    label: str
    cur: int
    source: SourceRef
    note: str = ""


class Financials(BaseModel):
    company_id: str
    fiscal_period: str
    basis: str
    unit: str = "千円"
    rounding: Rounding = "truncate_thousand"
    rounding_note: str = ""
    documents: dict[str, dict] = Field(default_factory=dict)
    items: dict[str, LineItem]
    supplementary: dict[str, SupplementaryItem] = Field(default_factory=dict)

    def value(self, key: str, period: str = "cur") -> int | None:
        item = self.items.get(key)
        return None if item is None else getattr(item, period)


# ---------------------------------------------------------------------------
# 主張と形式審査
# ---------------------------------------------------------------------------
Verdict = Literal["通過", "差し戻し", "退け"]


class Claim(BaseModel):
    """エージェントまたは人間の主張。"""

    speaker: str
    text: str
    sources: list[SourceRef] = Field(default_factory=list)
    settle_condition: str | None = None  # 何が観察されれば決着するか


class ReviewResult(BaseModel):
    verdict: Verdict
    reasons: list[str]
    valid_sources: list[SourceRef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 検算
# ---------------------------------------------------------------------------
CheckStatus = Literal["一致", "不一致", "未確認"]


class PeriodCheck(BaseModel):
    period: str
    computed: int | None
    reported: int | None
    diff: int | None
    tolerance: int
    status: CheckStatus


class CheckResult(BaseModel):
    group: str
    name: str
    n_components: int
    periods: list[PeriodCheck]
    status: CheckStatus
    missing: list[str] = Field(default_factory=list)


class ReconciliationReport(BaseModel):
    rounding: Rounding
    checks: list[CheckResult]

    @property
    def total(self) -> int:
        return len(self.checks)

    def count(self, status: CheckStatus) -> int:
        return sum(1 for c in self.checks if c.status == status)

    @property
    def rounding_diffs(self) -> int:
        return sum(1 for c in self.checks for p in c.periods if p.status == "一致" and p.diff not in (0, None))

    @property
    def passed(self) -> bool:
        """不一致が0件なら通過。未確認は通過を妨げないが、画面で明示する。"""
        return self.count("不一致") == 0


# ---------------------------------------------------------------------------
# 分析回次
# ---------------------------------------------------------------------------
RunStatus = Literal["open", "frozen"]


class RunMeta(BaseModel):
    run_id: str
    seq: int
    label: str
    as_of: str
    status: RunStatus = "open"
    parent: str | None = None
    created_at: str
    frozen_at: str | None = None
    trigger: str = ""


# ---------------------------------------------------------------------------
# 論争（Phase 3）
# ---------------------------------------------------------------------------
Phase = Literal["exploration", "triage_ready", "settlement"]
PHASE_ORDER: tuple[str, ...] = ("exploration", "triage_ready", "settlement")
AgentId = Literal["radar", "growth", "rebuild", "judge", "human"]
Action = Literal["提示", "提案", "攻撃", "防御", "譲歩", "宣告", "裁定", "比較", "介入"]
AgendaStatus = Literal["審理中", "決着", "保留"]


class CausalBridge(BaseModel):
    """定性の主張を数字につなぐ橋。「どの科目が、いくら、何か月後に動き、資金がいくら増減するか」。"""

    account: str                       # 標準科目のキー（合計行・利益行は不可）
    direction: Literal["増", "減"]
    amount: int                        # 科目の変動額（千円・正の数）。恒常的なら年額、一回限りならその額
    cf_effect: int                     # 資金への効果（千円）。正なら資金を生む。恒常的なら年額
    lead_months: int                   # 効果が出始めるまでの月数
    recurring: bool = True             # 毎年続く効果（経費削減など）か、一回限り（資産売却など）か
    rationale: str = ""


class TriageOption(BaseModel):
    """トリアージ（Level 0）の一つの道。何を残し、何を捨て、何が前提になるか。"""

    name: str                                              # 選択肢名（例：雇用死守型の第二会社方式）
    keep: list[str] = Field(default_factory=list)          # 残すもの（事業・雇用・取引先など）
    discard: list[str] = Field(default_factory=list)       # 捨てるもの（法人格・過大債務など）
    preconditions: list[str] = Field(default_factory=list)  # 前提条件（債権者同意、詐害行為取消リスクへの対処など）


class OptionAssessment(BaseModel):
    """トリアージの一つの道を、共通の物差しで評価したもの（Judge の比較）。どれかを選ぶことはしない。"""

    name: str
    employment: str = ""          # 雇用はどうなるか
    cash: str = ""                # 当面の資金繰りをどう乗り切るか（何がいつまでに要るか）
    creditors: str = ""           # 金融機関・債権者に何を求めるか
    months_needed: int | None = None   # 道筋がつくまでの月数（見込み）
    risks: list[str] = Field(default_factory=list)
    deciding_fact: str = ""       # この道を選ぶ（または捨てる）決め手になる観察事実
    sources: list[SourceRef] = Field(default_factory=list)
    in_time: bool | None = None   # 残余月数のうちに道筋がつくか（プログラムが判定）


class DebateMessage(BaseModel):
    id: str
    round: int
    phase: Phase
    speaker: AgentId
    action: Action
    text: str
    agenda_id: str | None = None
    target_node: str | None = None     # 決定木のノード
    sources: list[SourceRef] = Field(default_factory=list)
    settle_condition: str | None = None
    bridges: list[CausalBridge] = Field(default_factory=list)
    options: list[TriageOption] = Field(default_factory=list)   # トリアージ宣告の選択肢（Rebuild の宣告のみ）
    judge_note: JudgeNote | None = None                          # 裁定の構造化された中身（Judge の裁定のみ）
    addressee: AgentId | None = None                             # 人間の介入の宛先（指名された担当者が次に答える）
    comparison: list[OptionAssessment] = Field(default_factory=list)  # 選択肢の比較（Judge の比較のみ）
    at: str = ""                                                 # 発言の時刻（ISO 8601。記録が古いものは空）


def stamp() -> str:
    """発言の時刻。作られた時点でだけ付ける（古い記録を読み戻したときに現在時刻で埋めない）。"""
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


class Ruling(BaseModel):
    """Judge の判定。発言そのものは書き換えず、判定を別に積む。"""

    message_id: str
    round: int
    verdict: Verdict
    reasons: list[str] = Field(default_factory=list)


class AgendaItem(BaseModel):
    id: str
    title: str
    status: AgendaStatus = "審理中"
    opened_round: int
    closed_round: int | None = None
    resolution: str = ""


class CashBase(BaseModel):
    """財務データから決定論的に求めた資金の基礎値（千円）。改善案を反映する前の姿。"""

    liquid_funds: int | None           # 手元資金
    simple_cf: int | None              # 簡易営業CF（年）
    debt_service: int | None           # 約定返済（年）
    free_cf: int | None                # 返済後の資金収支（年）
    required_cf: int | None            # 必要CF（年）＝返済後収支の不足額。不足なしなら0
    basis: list[str] = Field(default_factory=list)    # 計算の根拠（式と出典）
    missing: list[str] = Field(default_factory=list)  # 取得できなかった科目

    @property
    def complete(self) -> bool:
        return self.required_cf is not None


class CountedBridge(BaseModel):
    message_id: str
    bridge: CausalBridge
    in_time: bool                      # 資金が尽きる前に効果が出るか


class Monitor(BaseModel):
    """裏の監視指標。画面にも出すが、判定はすべてプログラムが行う。"""

    base: CashBase
    accumulated_recovery_cf: int = 0   # 通過し、かつ間に合う恒常的改善の年間CF合計
    one_time_cash: int = 0             # 通過し、かつ間に合う一回限りの資金
    cash_runway_months: float | None = None  # 改善を反映した残余月数。None は資金流出なし
    base_runway_months: float | None = None  # 改善前の残余月数
    stalemate_count: int = 0
    rounds_completed: int = 0
    counted: list[CountedBridge] = Field(default_factory=list)
    levers_tried: list[str] = Field(default_factory=list)   # Growth が審査を通した提案で引いた改善レバー

    @property
    def gap(self) -> int | None:
        """必要CFに対する残りの不足額（年）。データ不足なら None。"""
        if self.base.required_cf is None:
            return None
        return max(0, self.base.required_cf - self.accumulated_recovery_cf)


class PhaseDecision(BaseModel):
    """フェーズ遷移の判定。プログラムが決め、Judge はこれを宣言・説明するだけ。"""

    round: int
    current: Phase
    next: Phase
    rule: str                          # 適用した規則の識別子
    reason: str                        # 数字を添えた説明
    stop_reason: str | None = None     # settlement に入るときの止まった理由の分類

    @property
    def changed(self) -> bool:
        return self.current != self.next


class JudgeNote(BaseModel):
    """Judge の裁定の中身。画面で整理して見せるため、文章とは別に数字と判定を残す（その時点の値）。"""

    tally: dict[str, int] = Field(default_factory=dict)     # 通過・差し戻し・退けの件数
    sent_back: list[str] = Field(default_factory=list)      # 通過しなかった発言と理由（1行ずつ）
    required_cf: int | None = None
    accumulated: int = 0
    gap: int | None = None
    runway: float | None = None
    stalemate: int = 0
    summary: str = ""                                       # Judge（LLM）の論点整理
    decision: PhaseDecision | None = None
    closing: str = ""                                       # 論争を閉じるときの一文


DebateMessage.model_rebuild()
