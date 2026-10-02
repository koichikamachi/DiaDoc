"""財務データから指標を計算する（決定論的）。

名目BS（帳簿どおり）と実質BS（帳簿＋実質化の調整）の二つの見方を返す。調整は、決算書の開示から作れるもの
（上場会社の評価差額金）と、人間が介入で入れるもの（株式・土地の含み損益、仮払金の減額など）だけ。
原資料の数値は加工しない（CLAUDE.md 6.9）。
"""

from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Sequence

from schema import ASSET_BLOCKS, Adjustment, CashBase, CausalBridge, CountedBridge, Financials, Monitor


def _v(fin: Financials, key: str, period: str = "cur") -> int:
    v = fin.value(key, period)
    return 0 if v is None else v


def interest_bearing_debt(fin: Financials) -> int:
    return sum(_v(fin, k) for k in ("stl", "cltd", "ltd", "cbond", "bond", "cls", "lls"))


def unrealized_gain_pretax(fin: Financials) -> int | None:
    """その他有価証券の含み益（税効果前）＝評価差額金＋それに係る繰延税金負債。"""
    dtl = fin.supplementary.get("dtl_on_unrealized_gain")
    if dtl is None:
        # 評価差額金がない（0または行なし）会社は含み益もない。ある会社で税効果注記が未取得なら計算できない
        return 0 if not fin.value("oci") else None
    return _v(fin, "oci") + dtl.cur


def disclosed_adjustments(fin: Financials) -> list[Adjustment]:
    """決算書に書かれた数字だけで作れる調整。

    その他有価証券を時価評価している会社（評価差額金がある会社）だけが対象。中小企業の多くは株式を
    取得原価のまま計上しており、外からは含み損益が分からないので、ここでは何もしない（人間の介入を待つ）。
    """
    gain = unrealized_gain_pretax(fin)
    if gain is None:
        raise ValueError("含み益に係る繰延税金負債（税効果注記）が未取得のため、実質BSを計算できません")
    if not gain:
        return []
    dta = fin.supplementary.get("dta_netted")
    out = [Adjustment(id="D1", account="投資有価証券（時価評価の含み益）", key="inv", block="投資その他の資産",
                      amount=-gain, origin="開示", note="評価差額金＋それに係る繰延税金負債（税効果注記）")]
    if dta and dta.cur:
        out.append(Adjustment(id="D2", account="繰延税金資産（相殺されていた分）", block="投資その他の資産",
                              amount=dta.cur, origin="開示", note="繰延税金負債と相殺表示されていた額を戻す"))
    if _v(fin, "dtl"):
        out.append(Adjustment(id="D3", account="繰延税金負債", key="dtl", block="固定負債", amount=-_v(fin, "dtl"),
                              origin="開示", note="含み益を除くので、それに係る税効果も除く"))
    return out


def real_adjustments(fin: Financials, extra: Sequence[Adjustment] = ()) -> list[Adjustment]:
    return disclosed_adjustments(fin) + list(extra)


def balance_sheet(fin: Financials, mode: str, extra: Sequence[Adjustment] = ()) -> dict:
    """名目（帳簿どおり）か実質（帳簿＋調整）の貸借対照表。extra は人間が入力した調整。"""
    ta, tl, inv = _v(fin, "ta"), _v(fin, "tl"), _v(fin, "inv")
    if mode == "nominal":
        na = _v(fin, "tna")
        note = "帳簿（原資料）どおり"
    else:
        adj = real_adjustments(fin, extra)
        ta += sum(a.amount for a in adj if a.is_asset)
        tl += sum(a.amount for a in adj if not a.is_asset)
        inv += sum(a.amount for a in adj if a.key == "inv")
        na = ta - tl if adj else _v(fin, "tna")
        note = ("推計：帳簿に次の調整を加えた（税効果は入力どおり）── " + "／".join(a.describe() for a in adj)
                if adj else "調整なし（帳簿どおり。株式などは取得原価で計上されている前提）")
    return {
        "総資産": ta, "負債": tl, "純資産": na, "投資有価証券": inv, "事業資産": ta - inv,
        "自己資本比率": na / ta if ta else 0.0,
        "営業利益ROA": _v(fin, "op") / ta if ta else 0.0,
        "注記": note,
    }


@dataclass(frozen=True)
class BSBlock:
    """比例縮尺の貸借対照表の一区画（千円）。side は "資産" か "負債・純資産"。

    adjust が空でない区画は調整の部分（斜線）。名目の列では「実質で除く部分」、実質の列では「実質で加わる部分」。
    """

    side: str
    kind: str        # 資産 / 負債 / 純資産
    label: str
    amount: int
    adjust: str = ""


def _book_blocks(fin: Financials) -> dict[str, int]:
    tca, cash, tinv = _v(fin, "tca"), _v(fin, "cash"), _v(fin, "tinv")
    return {"現金預金": cash, "その他の流動資産": tca - cash, "有形・無形固定資産": _v(fin, "ta") - tca - tinv,
            "投資その他の資産": tinv, "流動負債": _v(fin, "tcl"), "固定負債": _v(fin, "tl") - _v(fin, "tcl"),
            "純資産": _v(fin, "tna")}


def bs_blocks(fin: Financials, mode: str, extra: Sequence[Adjustment] = ()) -> list[BSBlock]:
    """貸借対照表を区画に分ける。帳簿の区画はそのまま（仮払金なども計上されている区画に入れたまま）。

    調整は区画ごとに、減らす分は名目の列に斜線で、増やす分は実質の列に斜線で重ねる。
    斜線を除いた部分（土台）は名目と実質で同じ高さになり、何が消え何が加わったかが見比べられる。
    """
    book = _book_blocks(fin)
    adj = real_adjustments(fin, extra)
    eq = [a.equity_effect for a in adj]
    parts: dict[str, list[tuple[str, int]]] = {k: [] for k in book}
    for a in adj:
        parts[a.block].append((a.account, a.amount))
    if adj:
        parts["純資産"] = [("調整による純資産の" + ("増加" if sum(eq) >= 0 else "減少"), sum(eq))]
    out: list[BSBlock] = []
    caps: list[BSBlock] = []
    for name, amount in book.items():
        side = "資産" if name in ASSET_BLOCKS else "負債・純資産"
        kind = "資産" if side == "資産" else ("純資産" if name == "純資産" else "負債")
        neg = [(n, d) for n, d in parts[name] if d < 0]
        pos = [(n, d) for n, d in parts[name] if d > 0]
        out.append(BSBlock(side, kind, name, amount + sum(d for _, d in neg)))
        for n, d in (neg if mode == "nominal" else pos):
            caps.append(BSBlock(side, kind, n, abs(d), "除く" if d < 0 else "加える"))
    return [b for b in out if b.amount != 0 or b.kind == "純資産"] + caps


# 実質化で確かめたい科目。図には帳簿どおり（計上されている区画のまま）入れ、ここで確かめる点を示す
WATCH_ITEMS = (
    ("inv", "投資有価証券", "投資その他の資産"),
    ("aff", "関係会社株式", "投資その他の資産"),
    ("land", "土地", "有形・無形固定資産"),
    ("suspense", "仮払金", "その他の流動資産"),
    ("ins_reserve", "保険積立金", "投資その他の資産"),
    ("officer_loan", "役員借入金", "固定負債"),
)
_WHY = {
    "inv": "取得原価で計上されている前提で扱っている。銘柄と時価が分かれば、含み益（＋）・含み損（−）を調整として入力する",
    "aff": "取得原価のまま。関係会社の財政状態が悪ければ、実質価値との差（−）を調整として入力する",
    "land": "取得原価のまま。路線価や鑑定で時価が分かれば、含み益・含み損を調整として入力する",
    "suspense": "中身と精算の見込みを確認する。資産性がなければ減額（−）を調整として入力する",
    "ins_reserve": "帳簿の額と解約返戻金の差を確かめ、差額を調整として入力する",
    "officer_loan": "負債のまま扱う。資本とみなすのは金融機関の見方で、実際には劣後化や債務免除などの手続きが要る。"
                    "手続きがあった時点で調整を入力する",
}


def watch_items(fin: Financials) -> list[tuple[str, str, int, str, str]]:
    """(key, 科目名, 帳簿の額, 区画, 確かめること)。評価差額金の開示がある会社の株式は、自動の調整済みと書く。"""
    gain = unrealized_gain_pretax(fin)
    out = []
    for key, label, block in WATCH_ITEMS:
        amount = fin.value(key)
        if not amount:
            continue
        why = _WHY[key]
        if key == "inv" and gain:
            why = (f"決算書に評価差額金 {_v(fin, 'oci'):,}千円の開示がある（時価評価済み）。"
                   "含み益を除く調整をプログラムが自動で入れている")
        out.append((key, label, amount, block, why))
    return out


def core_metrics(fin: Financials) -> dict:
    sales = _v(fin, "sales")
    return {
        "売上高": sales,
        "営業利益": _v(fin, "op"),
        "当期商品仕入高": _v(fin, "pur"),
        "前期商品仕入高": _v(fin, "pur", "prev"),
        "営業利益率": _v(fin, "op") / sales if sales else 0.0,
        "商品仕入高比率": _v(fin, "pur") / sales if sales else 0.0,
        "配当依存度": _v(fin, "div") / _v(fin, "ord") if _v(fin, "ord") else 0.0,
        "材料費比率": _v(fin, "mat") / _v(fin, "tmc") if _v(fin, "tmc") else 0.0,
        "販管費率": (_v(fin, "sell") + _v(fin, "adm")) / sales if sales else 0.0,
        "売上高成長率": sales / _v(fin, "sales", "prev") - 1 if _v(fin, "sales", "prev") else 0.0,
        "有利子負債": interest_bearing_debt(fin),
        "現金預金": _v(fin, "cash"),
    }


def company_ratios(fin: Financials, mode: str) -> dict[str, float]:
    """突合マトリクス用の比率。キーはベンチマークファイルと共通。"""
    m, bs = core_metrics(fin), balance_sheet(fin, mode)
    return {
        "op_margin": m["営業利益率"], "sga_ratio": m["販管費率"], "mat_ratio": m["材料費比率"],
        "purchase_ratio": m["商品仕入高比率"], "equity_ratio": bs["自己資本比率"], "div_dep": m["配当依存度"],
    }


# ---------------------------------------------------------------------------
# 資金の監視指標（論争の裏で動く。判定はすべてここと guardrails の決定論で行う）
# ---------------------------------------------------------------------------
DEBT_SERVICE_KEYS = ("cltd", "cbond", "cls")   # 1年以内の約定返済（長期借入金・社債・リース債務）
DEPRECIATION_KEYS = ("e_dep", "sga_dep")      # 製造原価と販管費の減価償却費
HORIZON_MONTHS = 120                          # 残余月数を追いかける上限
# 長期の残高と、その1年内返済の区分。長期の残高があるのに区分の行がなければ、約定返済は書類から確かめられない
# （中小企業の決算書は1年内返済分を分けずに全額を長期に載せることが多い。行がない＝返済がない、ではない）
LONG_TERM_PAIRS = (("ltd", "cltd", "長期借入金"), ("bond", "cbond", "社債"), ("lls", "cls", "リース債務"))
REFERENCE_YEARS = 10                          # 参考試算：確かめられない残高を何年の均等返済とみるか
PENDING_LABEL = "判定保留（返済予定表の開示待ち）"
DEBT_DOUBT = "BS記載に疑問あり、確認が必要"


def tri(v: int) -> str:
    """千円の額。マイナスは△で書く（決算書の書き方）。"""
    return f"△{abs(v):,}" if v < 0 else f"{v:,}"


def debt_doubt_text(base: CashBase) -> str:
    """約定返済が確かめられないことの説明（なければ空）。"""
    if not base.debt_unverified:
        return ""
    return f"約定返済：{DEBT_DOUBT}（{'・'.join(base.debt_unverified)}）"


def reference_text(base: CashBase) -> str:
    """判定保留のときに並べる参考試算（なければ空）。"""
    if base.ref_debt_service is None or base.ref_free_cf is None:
        return ""
    return (f"参考試算（例：{REFERENCE_YEARS}年均等返済なら年{base.ref_debt_service:,}千円、"
            f"返済後CF {tri(base.ref_free_cf)}千円）")


def cash_base(fin: Financials, repayment=None) -> CashBase:
    """改善案を反映する前の資金の姿（年額・千円）。

    簡易営業CF＝経常利益−法人税等＋減価償却費（特別損益は一回限りなので入れない）。
    返済後収支＝簡易営業CF−約定返済。不足額が必要CF。設備投資は見ていない（楽観側）ことを根拠に明記する。
    """
    missing: list[str] = []
    basis: list[str] = []

    def src(key: str) -> str:
        it = fin.items.get(key)
        return f"p.{it.source.page}" if it and it.source.page else "出典なし"

    def need(key: str) -> int | None:
        v = fin.value(key)
        if v is None:
            missing.append(key)
        return v

    cash, ordinary = need("cash"), need("ord")
    ctx = fin.value("ctx")
    if ctx is None:
        basis.append("法人税等（ctx）が未取得のため0として計算（楽観側）")
        ctx = 0
    dep = 0
    for k in DEPRECIATION_KEYS:
        v = fin.value(k)
        if v is None:
            basis.append(f"{k} が未取得のため0として計算（保守側）")
        else:
            dep += v
            basis.append(f"{k}＝{v:,}（{src(k)}）")
    debt = 0
    for k in DEBT_SERVICE_KEYS:
        v = fin.value(k)
        if v is not None:
            debt += v
            basis.append(f"{k}＝{v:,}（{src(k)}）")
    unverified: list[str] = []
    unverified_total = 0
    for long_key, cur_key, label in LONG_TERM_PAIRS:
        bal = fin.value(long_key)
        if bal and bal > 0 and fin.value(cur_key) is None:
            unverified.append(f"{label} {bal:,}千円に1年内返済の区分がない")
            unverified_total += bal
    confirmed = ""
    if repayment is not None:   # 支援担当者が返済予定表で確定した年間の約定返済（core.repayment）。書類から求めた額に代えて使う
        confirmed = (f"約定返済＝{repayment.amount:,}（支援担当者が返済予定表で確定：{repayment.basis}。"
                     f"書類から求めた額{debt:,}に代えて使う）")
        debt, unverified, unverified_total = repayment.amount, [], 0

    if cash is None or ordinary is None:
        return CashBase(liquid_funds=cash, simple_cf=None, debt_service=debt, free_cf=None, required_cf=None,
                        basis=basis + ["現金預金または経常利益がないため資金の判定はできません"], missing=missing)
    stl = fin.value("stl")
    if stl:
        basis.append(f"短期借入金 {stl:,}（{src('stl')}）は借り換え（折り返し）が続く前提で約定返済に含めていない。"
                     "金融機関が応じなければ、その額がただちに不足する")
    simple = ordinary - ctx + dep
    free = simple - debt
    ref_debt = ref_free = None
    if unverified:
        ref_debt = debt + unverified_total // REFERENCE_YEARS
        ref_free = simple - ref_debt
        repay = (f"約定返済＝{DEBT_DOUBT}（{'・'.join(unverified)}。書類で確かめられた返済は{debt:,}）"
                 f"　返済後収支＝{free:,}（確かめられない返済を0とした値。資金不足の有無は判定保留）"
                 f"　参考：{REFERENCE_YEARS}年均等返済なら年{ref_debt:,}、返済後{tri(ref_free)}")
    elif confirmed:
        repay = f"{confirmed}　返済後収支＝{free:,}"
    else:
        repay = f"約定返済＝{debt:,}　返済後収支＝{free:,}"
    basis = [f"手元資金＝現金預金 {cash:,}（{src('cash')}）",
             f"簡易営業CF＝経常利益 {ordinary:,}（{src('ord')}）−法人税等 {ctx:,}＋減価償却費 {dep:,}＝{simple:,}",
             repay] + basis + ["設備投資は含めていない（楽観側）"]
    return CashBase(liquid_funds=cash, simple_cf=simple, debt_service=debt, free_cf=free,
                    required_cf=max(0, -free), basis=basis, missing=missing,
                    debt_unverified=unverified, ref_debt_service=ref_debt, ref_free_cf=ref_free,
                    debt_confirmed=confirmed)


def _floor1(m: float | None) -> float | None:
    """残余月数は小数1桁に切り捨てて持つ（保守側。表示の「6.0か月」と判定の食い違いを防ぐ）。"""
    import math

    return None if m is None else math.floor(m * 10) / 10


def _runway(funds: int, free_cf: int, bridges: list[CausalBridge]) -> float | None:
    """月ごとに資金を追い、底をつくまでの月数を返す。尽きなければ None。

    恒常的な効果は lead_months の翌月から毎月（年額÷12）効く。一回限りの資金は lead_months の月末に入る
    （0 なら即時）。
    """
    cash = funds + sum(b.cf_effect for b in bridges if not b.recurring and b.lead_months <= 0)
    if cash < 0:
        return 0.0
    net = free_cf / 12
    for m in range(1, HORIZON_MONTHS + 1):
        net = (free_cf + sum(b.cf_effect for b in bridges if b.recurring and b.lead_months < m)) / 12
        before = cash
        cash += net
        if cash < 0:
            return (m - 1) + (before / -net)
        cash += sum(b.cf_effect for b in bridges if not b.recurring and b.lead_months == m)
        if cash < 0:
            return float(m)
    # 追いかける上限（120か月＝10年）のうちに尽きなければ、資金ショートのリスクは解消したものとして扱う。
    # 流出がわずかに残るとき、そのまま割り算で延ばすと「1.5万か月」のような意味のない数字になるため、ここで打ち切る
    return None


def runway_label(months: float | None, net_annual_cf: int | None = None, short: bool = False,
                 pending: bool = False) -> str:
    """残余月数の表示。上限（120か月）のうちに尽きないものは、流出があっても「資金ショートリスク解消」と出す。
    pending（約定返済が確かめられず、資金不足の有無を判定保留にしている）なら「資金流出なし」とは言い切らない。"""
    if months is None and pending:
        return "判定保留" if short else "判定保留（約定返済が未確認）"
    if months is not None:
        return f"{months:.1f}か月" if short else f"約{months:.1f}か月"
    if net_annual_cf is not None and net_annual_cf < 0:
        return "資金ショートリスク解消（10年超）" if not short else "リスク解消（10年超）"
    return "資金流出なし"


def net_after_improvement(m: Monitor) -> int | None:
    """改善を反映した返済後の年間資金収支（間に合う恒常的な改善だけ）。"""
    return None if m.base.free_cf is None else m.base.free_cf + m.accumulated_recovery_cf


def project(base: CashBase, passed: list[tuple[str, CausalBridge]], stalemate_count: int = 0,
            rounds_completed: int = 0) -> Monitor:
    """通過した因果ブリッジを反映した監視指標。

    資金が尽きた後に効き始める案は「間に合わない」として数えない。一回限りの資金が入ると残余月数が延び、
    それによって間に合うようになる案が出ることがあるので、収まるまで繰り返す。
    資金を減らす効果（先行投資など）は、間に合うかどうかに関係なく必ず数える（保守側）。
    """
    if not base.complete:
        return Monitor(base=base, stalemate_count=stalemate_count, rounds_completed=rounds_completed)
    base_runway = _floor1(_runway(base.liquid_funds, base.free_cf, []))
    in_time = {i: False for i in range(len(passed))}
    runway = base_runway
    for _ in range(len(passed) + 1):
        new = {i: (b.cf_effect < 0 or runway is None or b.lead_months < runway) for i, (_, b) in enumerate(passed)}
        runway = _floor1(_runway(base.liquid_funds, base.free_cf, [b for i, (_, b) in enumerate(passed) if new[i]]))
        if new == in_time:
            break
        in_time = new
    counted = [CountedBridge(message_id=mid, bridge=b, in_time=in_time[i]) for i, (mid, b) in enumerate(passed)]
    return Monitor(
        base=base,
        accumulated_recovery_cf=sum(c.bridge.cf_effect for c in counted if c.in_time and c.bridge.recurring),
        one_time_cash=sum(c.bridge.cf_effect for c in counted if c.in_time and not c.bridge.recurring),
        cash_runway_months=runway, base_runway_months=base_runway,
        stalemate_count=stalemate_count, rounds_completed=rounds_completed, counted=counted,
    )
