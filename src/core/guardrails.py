"""決定論的なガードレール（LLMを使わない部分）。

1. 検算ゲート: 読み取った財務数値の整合性を機械的に確かめ、不一致があれば論争に進ませない。
2. 形式審査: 主張に出典（ファイルと頁）と決着条件があるかを機械的に判定する。
3. 因果ブリッジの形式審査: 定性の主張が「科目・金額・月数」で数字につながっているか。
4. 膠着の検知、論点アジェンダの上限、フェーズ遷移の判定（Judge は判定を宣言・説明するだけ）。

CLAUDE.md 第6.2節・第6.7節の実装。
"""

from __future__ import annotations

from dataclasses import dataclass

from schema import (
    PHASE_ORDER,
    AgendaItem,
    CausalBridge,
    CheckResult,
    Claim,
    DebateMessage,
    Financials,
    Monitor,
    Phase,
    PhaseDecision,
    Ruling,
    PeriodCheck,
    ReconciliationReport,
    ReviewResult,
    Rounding,
    SourceRef,
)

# ---------------------------------------------------------------------------
# 許容差
# ---------------------------------------------------------------------------
MIN_TOLERANCE = 2


def tolerance(n_components: int, rounding: Rounding) -> int:
    """端数処理の規則から許容差（表示単位）を決める。

    - 千円未満切捨て・四捨五入の書類: 内訳n件の合計は報告合計と最大n単位ずれうる。
      許容差＝内訳件数n、ただし最低2。
    - 円単位の書類: 端数は生じないので0。
    """
    if rounding == "yen":
        return 0
    return max(MIN_TOLERANCE, n_components)


# ---------------------------------------------------------------------------
# 検算の定義
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Term:
    key: str
    sign: int = 1
    period: str | None = None  # None ならチェック対象の期。"prev" を指定すると前期値を使う
    optional: bool = False     # 行がない会社もある科目（短期借入金など）。なければ0とみなし、未確認にしない


@dataclass(frozen=True)
class Check:
    group: str
    name: str
    terms: tuple[Term, ...]
    reported: tuple[Term, ...]
    periods: tuple[str, ...] = ("prev", "cur")
    fixed_tolerance: int | None = None  # 表間連携などは件数によらず最低許容差で見る


def _t(*keys: str) -> tuple[Term, ...]:
    from tools.standard_accounts import OPTIONAL_KEYS

    out = []
    for k in keys:
        key, sign = (k[1:], -1) if k.startswith("-") else (k, 1)
        out.append(Term(key, sign, optional=key in OPTIONAL_KEYS))
    return tuple(out)


CHECKS: tuple[Check, ...] = (
    # 貸借対照表の内訳と合計
    Check("BS内訳", "流動資産合計", _t("cash", "nr", "ar", "fg", "wip", "rm", "pp", "oca", "ada1"), _t("tca")),
    Check("BS内訳", "有形固定資産合計", _t("bld", "str", "mac", "veh", "tool", "land", "lease", "cip"), _t("tppe")),
    Check("BS内訳", "無形固定資産合計", _t("sw", "oint"), _t("tint")),
    Check("BS内訳", "投資その他の資産合計", _t("inv", "aff", "cap", "ltl", "ltpp", "dep", "oinv", "ada2"), _t("tinv")),
    Check("BS内訳", "固定資産合計", _t("tppe", "tint", "tinv"), _t("tfa")),
    Check("BS内訳", "資産合計", _t("tca", "tfa"), _t("ta")),
    Check("BS内訳", "流動負債合計",
          _t("ap", "stl", "cltd", "cbond", "cls", "oap", "acc", "refund", "tax", "ctax", "wh", "dr", "bonus", "ocl"), _t("tcl")),
    Check("BS内訳", "固定負債合計", _t("bond", "ltd", "ltdep", "lls", "ret", "sbp", "dtl", "oltl"), _t("tltl")),
    Check("BS内訳", "負債合計", _t("tcl", "tltl"), _t("tl")),
    Check("BS内訳", "利益剰余金合計", _t("lr", "gr", "re"), _t("tre")),
    Check("BS内訳", "株主資本合計", _t("cs", "csr", "tre", "ts"), _t("tsh")),
    Check("BS内訳", "純資産合計", _t("tsh", "oci"), _t("tna")),
    # 貸借一致
    Check("貸借一致", "負債合計＋純資産合計＝負債純資産合計", _t("tl", "tna"), _t("tle")),
    Check("貸借一致", "資産合計＝負債純資産合計", _t("ta"), _t("tle")),
    # 損益の段階利益
    Check("段階利益", "売上総利益", _t("sales", "-cogs"), _t("gp")),
    Check("段階利益", "販管費合計", _t("sell", "adm"), _t("sga")),
    Check("段階利益", "営業利益", _t("gp", "-sga"), _t("op")),
    Check("段階利益", "営業外収益合計", _t("ii", "div", "ooi"), _t("tnoi")),
    Check("段階利益", "営業外費用合計", _t("ie", "bde", "idle", "ooe"), _t("tnoe")),
    Check("段階利益", "経常利益", _t("op", "tnoi", "-tnoe"), _t("ord")),
    Check("段階利益", "特別利益合計", _t("sg1", "sg2"), _t("tsg")),
    Check("段階利益", "特別損失合計", _t("sl1", "sl2", "sl3", "sl4", "sl5"), _t("tsl")),
    Check("段階利益", "税引前当期純利益", _t("ord", "tsg", "-tsl"), _t("pbt")),
    Check("段階利益", "法人税等合計", _t("ctx", "dtx"), _t("ttx")),
    Check("段階利益", "当期純利益", _t("pbt", "-ttx"), _t("ni")),
    # 製造原価から売上原価への流れ
    Check("原価の流れ", "当期総製造費用", _t("mat", "lab", "exp"), _t("tmc")),
    Check("原価の流れ", "当期製品製造原価", _t("tmc", "bwip", "-ewip"), _t("cgm")),
    Check("原価の流れ", "売上原価（調整表）", _t("bfg", "cgm", "pur", "-trf", "-efg", "-emd"), _t("cogs")),
    # 主要経営指標との照合
    Check("指標照合", "売上高", _t("sales"), _t("k_sales")),
    Check("指標照合", "当期純利益", _t("ni"), _t("k_ni")),
    Check("指標照合", "純資産額", _t("tna"), _t("k_na")),
    Check("指標照合", "総資産額", _t("ta"), _t("k_ta")),
    # 表間の連携（当期のみ）
    Check("表間連携", "貸借対照表の仕掛品＝製造原価の期末仕掛品", _t("wip"), _t("ewip"), ("cur",), MIN_TOLERANCE),
    Check("表間連携", "商品及び製品＝期末製品＋期末商品", _t("fg"), _t("efg", "emd"), ("cur",), MIN_TOLERANCE),
    # 前期末と当期首のつながり（当期のみ）
    Check("期首接続", "期首製品＝前期末の商品及び製品", _t("bfg"), (Term("fg", 1, "prev"),), ("cur",), MIN_TOLERANCE),
    Check("期首接続", "期首仕掛品＝前期末の仕掛品", _t("bwip"), (Term("wip", 1, "prev"),), ("cur",), MIN_TOLERANCE),
    Check("期首接続", "繰越利益剰余金の動き（前期末＋純利益−配当−別途積立＝当期末）",
          (Term("re", 1, "prev"), Term("ni"), Term("dvd", -1), Term("grt", -1)), _t("re"), ("cur",), MIN_TOLERANCE),
    Check("期首接続", "別途積立金の動き（前期末＋積立＝当期末）",
          (Term("gr", 1, "prev"), Term("grt")), _t("gr"), ("cur",), MIN_TOLERANCE),
)


def _sum(fin: Financials, terms: tuple[Term, ...], period: str) -> tuple[int | None, list[str]]:
    total, missing = 0, []
    for t in terms:
        v = fin.value(t.key, t.period or period)
        if v is None:
            if not t.optional:
                missing.append(t.key)
            continue
        total += t.sign * v
    return (None if missing else total), missing


def _present_count(fin: Financials, terms: tuple[Term, ...], period: str) -> int:
    return sum(1 for t in terms if fin.value(t.key, t.period or period) is not None)


def run_check(fin: Financials, check: Check) -> CheckResult:
    periods, all_missing = [], []
    for period in check.periods:
        computed, miss_c = _sum(fin, check.terms, period)
        reported, miss_r = _sum(fin, check.reported, period)
        all_missing += miss_c + miss_r
        n = _present_count(fin, check.terms, period)
        tol = check.fixed_tolerance if check.fixed_tolerance is not None else tolerance(n, fin.rounding)
        if fin.rounding == "yen":
            tol = 0
        if computed is None or reported is None:
            periods.append(PeriodCheck(period=period, computed=computed, reported=reported, diff=None,
                                       tolerance=tol, status="未確認"))
            continue
        diff = computed - reported
        periods.append(PeriodCheck(period=period, computed=computed, reported=reported, diff=diff,
                                   tolerance=tol, status="一致" if abs(diff) <= tol else "不一致"))
    statuses = {p.status for p in periods}
    status = "不一致" if "不一致" in statuses else ("未確認" if "未確認" in statuses else "一致")
    return CheckResult(group=check.group, name=check.name, n_components=len(check.terms),
                       periods=periods, status=status, missing=sorted(set(all_missing)))


def reconcile(fin: Financials, checks: tuple[Check, ...] = CHECKS) -> ReconciliationReport:
    """検算ゲート。全チェックを実行して結果を返す。report.passed が False なら論争に進まない。"""
    return ReconciliationReport(rounding=fin.rounding, checks=[run_check(fin, c) for c in checks])


# ---------------------------------------------------------------------------
# 形式審査
# ---------------------------------------------------------------------------
TRIVIAL_SETTLE = {"", "なし", "無し", "不明", "特になし", "-", "―", "—", "n/a", "na", "none"}


def review_claim(claim: Claim) -> ReviewResult:
    """審判の形式審査。中身の賛否には立ち入らない。

    1. 出典（ファイルと頁の両方）がひとつもない → 退け
    2. 決着条件（何が観察されれば決着するか）がない → 差し戻し
    3. 両方そろう → 通過（中身の審理へ）
    """
    valid = [s for s in claim.sources if s.is_complete()]
    incomplete = [s for s in claim.sources if not s.is_complete()]
    reasons: list[str] = []
    if not valid:
        if incomplete:
            reasons.append("出典に書類名または頁が欠けています：" + "、".join(s.label() for s in incomplete))
        else:
            reasons.append("出典が示されていません")
        return ReviewResult(verdict="退け", reasons=reasons)
    settle = (claim.settle_condition or "").strip()
    if settle.lower() in TRIVIAL_SETTLE:
        reasons.append("何が観察されれば決着するか（決着条件）が示されていません")
        return ReviewResult(verdict="差し戻し", reasons=reasons, valid_sources=valid)
    reasons.append("出典と決着条件がそろっています。中身の審理に進みます")
    if incomplete:
        reasons.append("ただし不完全な出典は審理に使いません：" + "、".join(s.label() for s in incomplete))
    return ReviewResult(verdict="通過", reasons=reasons, valid_sources=valid)


def parse_source(text: str) -> SourceRef:
    """「有報第73期 p.93」のような表記を SourceRef に変換する。頁がなければ page=None。"""
    import re

    text = (text or "").strip()
    m = re.search(r"^(.*?)[\s　]*(?:p\.?|P\.?|頁|ページ)[\s　]*([0-9０-９]+(?:[–\-〜~][0-9０-９]+)?)\s*$", text)
    if m:
        return SourceRef(file=m.group(1).strip() or None, page=m.group(2))
    m = re.search(r"^(.*?)[\s　]*([0-9０-９]+(?:[–\-〜~][0-9０-９]+)?)[\s　]*(?:頁|ページ)\s*$", text)
    if m:
        return SourceRef(file=m.group(1).strip() or None, page=m.group(2))
    return SourceRef(file=text or None, page=None)


# ---------------------------------------------------------------------------
# 因果ブリッジの形式審査
# ---------------------------------------------------------------------------
REVENUE_KEYS = frozenset({"sales", "ii", "div", "ooi", "sg1", "sg2"})
ASSET_SECTIONS = frozenset({"流動資産", "有形固定資産", "無形固定資産", "投資その他"})
LIABILITY_SECTIONS = frozenset({"流動負債", "固定負債"})
EXPENSE_STATEMENTS = frozenset({"販管費内訳", "製造原価"})
NOT_BRIDGEABLE_SECTIONS = frozenset({"利益", "仕掛品"})
LIABILITY_WATCH = frozenset({"officer_loan"})
NON_CASH_KEYS = frozenset({"e_dep", "sga_dep", "idle", "bde", "sl1", "sl3", "dtx", "ada1", "ada2", "cash"})
# 資金の出入りを伴わない費用・引当金と、資金そのもの（原因ではなく結果なので橋の起点にしない）


def cash_sign(account: str, direction: str) -> int | None:
    """科目がその向きに動いたとき、資金が増えるなら +1、減るなら -1。橋を架けられない科目は None。"""
    from tools.standard_accounts import META, TOTAL_KEYS

    if account not in META or account in TOTAL_KEYS or account in NON_CASH_KEYS:
        return None
    statement, section = META[account]
    up = 1 if direction == "増" else -1
    if statement == "BS":
        if section in ASSET_SECTIONS:
            return -up
        if section in LIABILITY_SECTIONS or section == "純資産":
            return up
        return None
    if statement == "勘定科目内訳":
        return up if account in LIABILITY_WATCH else -up
    if statement == "PL":
        if section in NOT_BRIDGEABLE_SECTIONS:
            return None
        return up if account in REVENUE_KEYS else -up
    if statement in EXPENSE_STATEMENTS and section not in NOT_BRIDGEABLE_SECTIONS:
        return -up
    if account == "pur":
        return -up
    return None


def _is_stock(account: str) -> bool:
    from tools.standard_accounts import META

    return META.get(account, ("", ""))[0] in ("BS", "勘定科目内訳")


def check_bridge(b: CausalBridge) -> list[str]:
    """問題点の一覧を返す。空なら形式上は通る（中身の妥当性は Judge の審理で見る）。"""
    from tools.standard_accounts import LABELS

    problems: list[str] = []
    sign = cash_sign(b.account, b.direction)
    name = LABELS.get(b.account, b.account)
    if sign is None:
        problems.append(f"「{name}」は影響する科目として使えません（標準科目の個別科目を指定してください。合計行・利益行と、減価償却費など資金の出入りを伴わない科目は不可）")
    if b.amount <= 0:
        problems.append(f"「{name}」の変動額が0以下です")
    if b.lead_months < 0:
        problems.append(f"「{name}」の所要月数が負です")
    if b.cf_effect == 0:
        problems.append(f"「{name}」の資金効果が0です")
    elif abs(b.cf_effect) > b.amount > 0 and not _is_stock(b.account):
        # 損益の科目は「科目の変動額」を超える資金は生まない。資産の売却は簿価を超える入金（売却益）がありうるので対象外
        problems.append(f"「{name}」の資金効果 {b.cf_effect:,} が科目の変動額 {b.amount:,} を超えています")
    if sign is not None and b.cf_effect != 0 and (b.cf_effect > 0) != (sign > 0):
        problems.append(f"「{name}」が{b.direction}えると資金は{'増える' if sign > 0 else '減る'}はずですが、資金効果の符号が逆です")
    return problems


BRIDGE_REQUIRED = {("growth", "提案"), ("rebuild", "提案")}


def review_debate_message(msg: DebateMessage) -> ReviewResult:
    """論争の発言の形式審査（機械の段）。出典と決着条件、そして改善案には因果ブリッジを求める。"""
    base = review_claim(Claim(speaker=msg.speaker, text=msg.text, sources=msg.sources,
                              settle_condition=msg.settle_condition))
    if base.verdict != "通過":
        return base
    reasons: list[str] = []
    if (msg.speaker, msg.action) in BRIDGE_REQUIRED and not msg.bridges:
        reasons.append("改善案に、影響する勘定科目・金額・所要月数（因果ブリッジ）が示されていません。金額と経路のない定性論は審理できません")
    for b in msg.bridges:
        reasons += check_bridge(b)
    if reasons:
        return ReviewResult(verdict="差し戻し", reasons=reasons, valid_sources=base.valid_sources)
    return base


# ---------------------------------------------------------------------------
# フェーズの規律（発言の中身ではなく、段階ごとに言ってよいことの枠）
# ---------------------------------------------------------------------------
TRIAGE_WORDS = ("解体", "清算", "法的整理", "民事再生", "破産", "第二会社", "Level 0", "Level0", "レベル0", "廃業")


def phase_discipline(msg: DebateMessage) -> list[str]:
    """段階ごとの規律に反していれば理由を返す。

    - 探索段階の Rebuild は、トリアージの語（解体・法的整理・第二会社など）を口にしない（潜伏型トリアージ）
    - 「宣告」は、トリアージ段階の Rebuild だけが行える
    """
    problems: list[str] = []
    if msg.speaker == "rebuild" and msg.phase == "exploration":
        hit = [w for w in TRIAGE_WORDS if w.lower() in msg.text.lower()]
        if hit:
            problems.append("探索段階では、資金の数字で改善案を検証するまでトリアージの語（" + "・".join(hit) + "）を使えません")
    if msg.action == "宣告" and not (msg.speaker == "rebuild" and msg.phase == "triage_ready"):
        problems.append("「宣告」はトリアージ段階の Dr. Rebuild だけが行えます")
    elif msg.action == "宣告":
        if len(msg.options) < 2:
            problems.append("トリアージの宣告には、比べられる道を二つ以上（選択肢名・残すもの・捨てるもの・前提条件）示してください")
        lacking = [o.name or "（名称なし）" for o in msg.options if not o.preconditions or not o.name.strip()]
        if lacking:
            problems.append("前提条件が書かれていない道があります：" + "、".join(lacking))
    return problems


# ---------------------------------------------------------------------------
# 4大改善レバー（Growth の「あがき」を数える物差し）
# ---------------------------------------------------------------------------
LEVERS: tuple[str, ...] = ("売上・粗利", "原価・現場", "固定費・販管費", "資産売却・BS")
_REVENUE_LEVER = frozenset({"sales", "ii", "div", "ooi", "sg1", "sg2"})
_FIXED_EXTRA = frozenset({"sell", "adm", "ie", "ooe", "bde"})


def lever_of(account: str) -> str | None:
    """科目がどの改善レバーに属するか（決定論）。

    売上・粗利＝売上と営業外の収益、原価・現場＝製造原価と仕入、固定費・販管費＝販管費内訳と支払利息など、
    資産売却・BS＝貸借対照表の科目（遊休資産の売却、在庫・売掛金の圧縮など）と監視科目。
    """
    from tools.standard_accounts import META

    if account in _REVENUE_LEVER:
        return "売上・粗利"
    statement = META.get(account, ("", ""))[0]
    if statement in ("製造原価", "売上原価調整") or account in ("cogs", "mat", "lab", "exp", "pur"):
        return "原価・現場"
    if statement == "販管費内訳" or account in _FIXED_EXTRA:
        return "固定費・販管費"
    if statement in ("BS", "勘定科目内訳"):
        return "資産売却・BS"
    return None


def levers_tried(messages: list[DebateMessage], rulings: list[Ruling]) -> list[str]:
    """Growth の提案のうち審査を通過したもので、触れた改善レバー（LEVERS の順）。"""
    latest: dict[str, str] = {}
    for r in rulings:
        latest[r.message_id] = r.verdict
    found = {lever_of(b.account) for m in messages
             if m.speaker == "growth" and m.action == "提案" and latest.get(m.id) == "通過" for b in m.bridges}
    return [lv for lv in LEVERS if lv in found]


# ---------------------------------------------------------------------------
# 膠着の検知と論点アジェンダ
# ---------------------------------------------------------------------------
MAX_OPEN_AGENDA = 3
DEBATERS = frozenset({"growth", "rebuild"})


class AgendaFullError(ValueError):
    pass


def _norm_text(t: str) -> str:
    return "".join((t or "").split()).rstrip("。．.")


def update_stalemate(prev_count: int, round_no: int, messages: list[DebateMessage], rulings: list[Ruling]) -> int:
    """そのラウンドに「新しく通過した主張」がなければ +1、あれば 0 に戻す。

    数えるのは論争の当事者（Growth と Rebuild）の主張だけ。Radar の事実提示、Judge の裁定、人間の介入は数えない。
    以前に通過した主張と同じ文面の繰り返しは、新しい主張として数えない。
    """
    by_id = {m.id: m for m in messages}
    passed_before = {_norm_text(by_id[r.message_id].text) for r in rulings
                     if r.verdict == "通過" and r.round < round_no and r.message_id in by_id}
    fresh = [r for r in rulings if r.round == round_no and r.verdict == "通過" and r.message_id in by_id
             and by_id[r.message_id].speaker in DEBATERS
             and _norm_text(by_id[r.message_id].text) not in passed_before]
    return 0 if fresh else prev_count + 1


def open_agenda(agenda: list[AgendaItem], item: AgendaItem) -> list[AgendaItem]:
    """審理中の論点は最大3件。超えるなら、どれかを決着か保留にしてから開く。"""
    if item.status == "審理中" and sum(1 for a in agenda if a.status == "審理中") >= MAX_OPEN_AGENDA:
        raise AgendaFullError(f"審理中の論点は{MAX_OPEN_AGENDA}件までです。いずれかを決着または保留にしてください")
    if any(a.id == item.id for a in agenda):
        raise ValueError(f"論点 {item.id} は既にあります")
    return agenda + [item]


def close_agenda(agenda: list[AgendaItem], agenda_id: str, status: str, round_no: int,
                 resolution: str = "") -> list[AgendaItem]:
    out = []
    for a in agenda:
        if a.id == agenda_id:
            a = a.model_copy(update={"status": status, "closed_round": round_no, "resolution": resolution})
        out.append(a)
    return out


# ---------------------------------------------------------------------------
# フェーズ遷移の判定（決定論）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PhasePolicy:
    gap_check_round: int = 2      # このラウンドを終えても必要CFに届かなければトリアージへ
    stalemate_limit: int = 2      # 膠着がこの回数に達したら探索を打ち切る
    max_rounds: int = 4           # 探索の上限ラウンド数（CLAUDE.md の未決事項。仮置き）
    triage_grace: int = 2         # トリアージ段階で宣告が成り立たないまま過ぎてよいラウンド数
    require_all_levers: bool = True   # 4大改善レバーをすべて試すまでトリアージに進まない（上限ラウンドを除く）


DEFAULT_POLICY = PhasePolicy()


def _fmt_runway(m: float | None) -> str:
    return "資金流出なし" if m is None else f"{m:.1f}か月"


def decide_phase(phase: Phase, monitor: Monitor, triage_declared: bool = False,
                 policy: PhasePolicy = DEFAULT_POLICY) -> PhaseDecision:
    """ラウンドの終わりに呼ぶ。フェーズは前にしか進まない。

    トリアージに入るのは「資金の不足が数字で示されている」ときだけ。資金データがない、または不足がない会社は、
    膠着や上限到達で探索を終えても settlement に進み、トリアージは起きない（CLAUDE.md 6.1 根拠なしに進まない）。
    """
    r = monitor.rounds_completed
    gap = monitor.gap
    req = monitor.base.required_cf
    acc = monitor.accumulated_recovery_cf
    nums = (f"必要CF {req:,}／回収CF累計 {acc:,}（年・千円）、残余月数 {_fmt_runway(monitor.cash_runway_months)}"
            if req is not None else "資金データ不足のため必要CFは判定できません")

    def d(nxt: Phase, rule: str, reason: str, stop: str | None = None) -> PhaseDecision:
        assert PHASE_ORDER.index(nxt) >= PHASE_ORDER.index(phase), "フェーズは後戻りしない"
        return PhaseDecision(round=r, current=phase, next=nxt, rule=rule, reason=f"{reason}　［{nums}］",
                             stop_reason=stop)

    if phase == "settlement":
        return d("settlement", "terminal", "既に決着段階です")
    if phase == "triage_ready":
        if triage_declared:
            return d("settlement", "triage_declared", "トリアージが宣告されたため、選択肢の比較に移ります", "トリアージ宣告")
        if r >= policy.max_rounds + policy.triage_grace:
            return d("settlement", "triage_not_declared", "トリアージの宣告が審査を通らないまま上限に達しました",
                     "宣告不成立（上限到達）")
        return d("triage_ready", "await_triage", "トリアージの宣告を待っています")

    short = gap is not None and req > 0 and gap > 0
    missing = [lv for lv in LEVERS if lv not in monitor.levers_tried] if policy.require_all_levers else []
    pressed = r >= policy.gap_check_round or monitor.stalemate_count >= policy.stalemate_limit
    if short and pressed and not missing:
        if r >= policy.gap_check_round:
            return d("triage_ready", "gap_unmet",
                     f"4つの改善レバーをすべて試し、{r}ラウンドを終えても、改善案の合計が必要CFに{gap:,}千円届きません")
        return d("triage_ready", "stalemate_with_gap",
                 f"4つの改善レバーを試したうえで議論が{monitor.stalemate_count}回続けて膠着し、資金の不足も残っています")
    if short and r >= policy.max_rounds:
        note = f"（未着手のレバー：{'・'.join(missing)}）" if missing else ""
        return d("triage_ready", "gap_unmet_at_limit",
                 f"上限の{policy.max_rounds}ラウンドに達しても、必要CFに{gap:,}千円届きません{note}")
    if short and pressed and missing:
        return d("exploration", "levers_remaining",
                 f"必要CFに{gap:,}千円届きませんが、まだ引いていない改善レバーがあります：{'・'.join(missing)}。探索を続けます")
    if gap is not None and req > 0 and gap == 0:
        return d("settlement", "gap_closed", "通過した改善案で必要CFを満たしました", "改善策で充足")
    if monitor.stalemate_count >= policy.stalemate_limit:
        why = "資金の不足は示されていない" if gap is not None else "資金データが不足している"
        return d("settlement", "stalemate_no_gap", f"議論が{monitor.stalemate_count}回続けて膠着しました。{why}ためトリアージには進みません",
                 "膠着（資金不足なし）" if gap is not None else "膠着（資金データ不足）")
    if r >= policy.max_rounds:
        return d("settlement", "max_rounds", f"上限の{policy.max_rounds}ラウンドに達しました", "上限到達")
    return d("exploration", "continue", "探索を続けます")
