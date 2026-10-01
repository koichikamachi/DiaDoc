"""データ構造の定義（Pydantic v2）。

財務データ、出典、主張と形式審査の判定、検算結果、分析回次のメタ情報を扱う。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class RoundingAdjustment(BaseModel):
    """人が承認した端数調整差額（検算ゲートの「軽微な差異」を吸収する記録）。

    書類に書かれた合計は正として残し、内訳の合計とのずれを、この行で埋める。
    booked_to は計上先の区分（その他流動資産・その他流動負債・雑損益）。
    """

    group: str
    check: str
    period: str                 # prev / cur
    amount: int                 # 計算値 + amount ＝ 報告値（表示単位）
    booked_to: str
    approved_by: str = "人間（ライム）"
    approved_at: str = ""
    file: str = ""


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
    rounding_adjustments: list[RoundingAdjustment] = Field(default_factory=list)

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
    adjusted: int = 0           # 承認された端数調整差額（計算値に加えた額）


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
    def adjusted_count(self) -> int:
        """人が承認した端数調整差額で一致させた項目の数。"""
        return sum(1 for c in self.checks for p in c.periods if p.adjusted)

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


MAX_AMOUNT = 999_999_999   # 金額欄の上限（千円・9桁＝約1兆円）。生成の暴走（000… の羅列）を受け付けない


def bounded_amount(v: int | None) -> int | None:
    if v is not None and abs(v) > MAX_AMOUNT:
        raise ValueError(f"金額が大きすぎます（千円単位・9桁以内で書いてください）：{v}")
    return v


class CausalBridge(BaseModel):
    """定性の主張を数字につなぐ橋。「どの科目が、いくら、何か月後に動き、資金がいくら増減するか」。"""

    account: str                       # 標準科目のキー（合計行・利益行は不可）
    direction: Literal["増", "減"]
    amount: int = Field(ge=-MAX_AMOUNT, le=MAX_AMOUNT, description="科目の変動額（千円・正の整数・9桁以内）")   # 恒常的なら年額、一回限りならその額
    cf_effect: int = Field(ge=-MAX_AMOUNT, le=MAX_AMOUNT, description="資金への効果（千円・整数・9桁以内）。正なら資金を生む")   # 恒常的なら年額
    lead_months: int = Field(description="効果が出始めるまでの月数（0以上の整数）")
    recurring: bool = True             # 毎年続く効果（経費削減など）か、一回限り（資産売却など）か
    rationale: str = ""

    @field_validator("amount", "cf_effect")
    @classmethod
    def _bounded(cls, v: int) -> int:
        return bounded_amount(v)


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
    headline: str = ""                  # 提案の見出し（24字以内。提案のとき）
    agenda_id: str | None = None
    target_node: str | None = None     # 決定木のノード
    sources: list[SourceRef] = Field(default_factory=list)
    settle_condition: str | None = None
    bridges: list[CausalBridge] = Field(default_factory=list)
    options: list[TriageOption] = Field(default_factory=list)   # トリアージ宣告の選択肢（Rebuild の宣告のみ）
    judge_note: JudgeNote | None = None                          # 裁定の構造化された中身（Judge の裁定のみ）
    addressee: AgentId | None = None                             # 人間の介入の宛先（指名された担当者が次に答える）
    comparison: list[OptionAssessment] = Field(default_factory=list)  # 選択肢の比較（Judge の比較のみ）
    target_message: str | None = None      # 攻撃・防御の相手の発言ID（攻撃なら疑義を向けた提案、防御なら受けた攻撃）
    challenged_account: str | None = None  # 攻撃が疑義を向けた科目（なければ提案全体）
    feasible_cf: int | None = None         # 攻撃する側が現実的と見る資金効果（年・千円）。0 は「見込めない」
    at: str = ""                                                 # 発言の時刻（ISO 8601。記録が古いものは空）


# ---------------------------------------------------------------------------
# 実質化の調整（帳簿の額に人間が加える修正。例：株式の含み益、仮払金の減額）
# ---------------------------------------------------------------------------
BSBlockName = Literal["現金預金", "その他の流動資産", "有形・無形固定資産", "投資その他の資産", "流動負債", "固定負債"]
ASSET_BLOCKS: tuple[str, ...] = ("現金預金", "その他の流動資産", "有形・無形固定資産", "投資その他の資産")
LIABILITY_BLOCKS: tuple[str, ...] = ("流動負債", "固定負債")


class Adjustment(BaseModel):
    """実質BSへの調整一件（千円）。資産か負債の区画を増減させ、差額はすべて純資産に効く。

    origin="開示" は決算書に書かれた数字からプログラムが作る調整（上場会社の評価差額金など）。
    origin="人間" は介入として入力された調整。税効果は考慮せず、入力された額をそのまま使う。
    """

    id: str
    account: str                 # 科目名（表示用）
    key: str | None = None       # 標準科目のキー（分かれば）
    block: BSBlockName
    amount: int                  # 区画を増やすなら正、減らすなら負
    note: str = ""               # 根拠
    origin: Literal["人間", "開示"] = "人間"
    at: str | None = None
    message_id: str | None = None   # 論争に書き込んだ介入の発言ID

    @property
    def is_asset(self) -> bool:
        return self.block in ASSET_BLOCKS

    @property
    def equity_effect(self) -> int:
        return self.amount if self.is_asset else -self.amount

    def describe(self) -> str:
        sign = "+" if self.amount >= 0 else "−"
        return f"{self.account} {sign}{abs(self.amount):,}千円（{self.block}）" + (f"：{self.note}" if self.note else "")


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
    by: Literal["review", "challenge"] = "review"   # 発言そのものの審査か、審査を通った反論による見直しか
    adjusted_bridges: list[CausalBridge] | None = None   # 減額採択：反論を受けて数える因果ブリッジ（資金効果を減らしたもの）

    @property
    def reduced(self) -> bool:
        return self.verdict == "通過" and self.adjusted_bridges is not None


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
    # 約定返済が書類から確かめられないもの（長期の残高はあるのに1年内返済の区分がない）。例：「長期借入金 100,000」
    debt_unverified: list[str] = Field(default_factory=list)
    ref_debt_service: int | None = None   # 参考試算：確かめられない残高を10年均等で返すと仮定した年間の返済（既知の返済を含む）
    ref_free_cf: int | None = None        # 参考試算：そのときの返済後の資金収支（年）
    debt_confirmed: str = ""              # 人間が返済予定表で確定した約定返済（core.repayment）の説明。確定していなければ空

    @property
    def complete(self) -> bool:
        return self.required_cf is not None

    @property
    def shortage_pending(self) -> bool:
        """資金不足の有無を判定保留にするか。返済0とみなしても不足が出ていないのに、約定返済が確かめられないとき。
        （0とみなしても不足なら、返済を入れれば不足はさらに大きいので、不足は確かである）"""
        return bool(self.debt_unverified) and self.free_cf is not None and self.free_cf >= 0


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
    one_time: int = 0                                       # 一括調達（一時的資金）：資産売却などの一回限りの資金
    pending: str = ""                                       # 資金不足の有無を判定保留にしている理由（なければ空）
    reference: str = ""                                     # 判定保留のときの参考試算
    confirmed: str = ""                                     # 人間が返済予定表で確定した約定返済（あれば）
    summary: str = ""                                       # Judge（LLM）の論点整理
    decision: PhaseDecision | None = None
    closing: str = ""                                       # 論争を閉じるときの一文


DebateMessage.model_rebuild()
