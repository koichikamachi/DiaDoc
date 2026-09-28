"""財務データから指標を計算する（決定論的）。

名目BS（原資料どおり）と実質本業BS（株式含み益を控除）の二つの見方を返す。
原資料の数値は加工せず、実質本業BSは補助計算として別に示す（CLAUDE.md 6.9）。
"""

from __future__ import annotations

from dataclasses import dataclass

from schema import CashBase, CausalBridge, CountedBridge, Financials, Monitor


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


def balance_sheet(fin: Financials, mode: str) -> dict:
    if mode == "nominal":
        ta, tl, inv, na = _v(fin, "ta"), _v(fin, "tl"), _v(fin, "inv"), _v(fin, "tna")
        note = "原資料どおり（その他有価証券は時価評価、税効果会計適用）"
    else:
        gain = unrealized_gain_pretax(fin)
        if gain is None:
            raise ValueError("含み益に係る繰延税金負債（税効果注記）が未取得のため、実質本業BSを計算できません")
        dta = fin.supplementary.get("dta_netted")
        dta_v = dta.cur if dta else 0
        ta = _v(fin, "ta") - gain + dta_v
        tl = _v(fin, "tl") - _v(fin, "dtl")
        inv = _v(fin, "inv") - gain
        na = ta - tl
        note = (f"推計：含み益（税効果前）{gain:,}千円を資産から控除し、対応する繰延税金負債を除去、"
                "相殺されていた繰延税金資産を資産に戻した。純資産は株主資本合計に一致する")
    return {
        "総資産": ta, "負債": tl, "純資産": na, "投資有価証券": inv, "事業資産": ta - inv,
        "自己資本比率": na / ta if ta else 0.0,
        "営業利益ROA": _v(fin, "op") / ta if ta else 0.0,
        "注記": note,
    }


@dataclass(frozen=True)
class BSBlock:
    """比例縮尺の貸借対照表の一区画（千円）。side は "資産" か "負債・純資産"。"""

    side: str
    kind: str        # 資産 / 負債 / 純資産
    label: str
    amount: int
    gain_related: bool = False   # 株式の含み益に由来する区画（名目にだけある）


def bs_blocks(fin: Financials, mode: str) -> list[BSBlock]:
    """貸借対照表を区画に分ける。区画の合計は balance_sheet() の総資産・負債＋純資産に一致する。

    名目では含み益・繰延税金負債・評価差額金を別区画にして、実質で何が消えるかを見せる。
    """
    bs = balance_sheet(fin, mode)
    ta, tca, tinv, cash = bs["総資産"], _v(fin, "tca"), _v(fin, "tinv"), _v(fin, "cash")
    tcl, tltl, dtl, oci = _v(fin, "tcl"), _v(fin, "tltl"), _v(fin, "dtl"), _v(fin, "oci")
    gain = unrealized_gain_pretax(fin) or 0
    if mode == "nominal":
        inv_other = tinv - gain
        fixed = ta - tca - tinv
    else:
        dta = fin.supplementary.get("dta_netted")
        inv_other = tinv - gain + (dta.cur if dta else 0)
        fixed = ta - tca - inv_other
    blocks = [
        BSBlock("資産", "資産", "現金預金", cash),
        BSBlock("資産", "資産", "その他の流動資産", tca - cash),
        BSBlock("資産", "資産", "有形・無形固定資産", fixed),
        BSBlock("資産", "資産", "投資その他の資産", inv_other),
    ]
    if mode == "nominal" and gain:
        blocks.append(BSBlock("資産", "資産", "株式の含み益", gain, True))
    blocks.append(BSBlock("負債・純資産", "負債", "流動負債", tcl))
    if mode == "nominal":
        blocks.append(BSBlock("負債・純資産", "負債", "固定負債",
                              tltl - (dtl if gain else 0)))
        if gain and dtl:
            blocks.append(BSBlock("負債・純資産", "負債", "繰延税金負債", dtl, True))
        na = bs["純資産"]
        if gain and oci:
            blocks.append(BSBlock("負債・純資産", "純資産", "純資産", na - oci))
            blocks.append(BSBlock("負債・純資産", "純資産", "評価差額金", oci, True))
        else:
            blocks.append(BSBlock("負債・純資産", "純資産", "純資産", na))
    else:
        blocks.append(BSBlock("負債・純資産", "負債", "固定負債", bs["負債"] - tcl))
        blocks.append(BSBlock("負債・純資産", "純資産", "純資産", bs["純資産"]))
    return [b for b in blocks if b.amount != 0 or b.kind == "純資産"]


# 実質化で本来検討すべき中小企業の科目（いまの実質本業BSには反映していない）
WATCH_ITEMS = (
    ("suspense", "仮払金", "中身と回収見込みの確認が要る（資産性がなければ減額）"),
    ("officer_loan", "役員借入金", "返済を求めない約束があれば、実質は資本に近い"),
    ("ins_reserve", "保険積立金", "帳簿の額と解約返戻金の差を確かめる"),
)


def watch_items(fin: Financials) -> list[tuple[str, int, str]]:
    return [(label, fin.value(key), why) for key, label, why in WATCH_ITEMS if fin.value(key)]


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


def cash_base(fin: Financials) -> CashBase:
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

    if cash is None or ordinary is None:
        return CashBase(liquid_funds=cash, simple_cf=None, debt_service=debt, free_cf=None, required_cf=None,
                        basis=basis + ["現金預金または経常利益がないため資金の判定はできません"], missing=missing)
    stl = fin.value("stl")
    if stl:
        basis.append(f"短期借入金 {stl:,}（{src('stl')}）は借り換え（折り返し）が続く前提で約定返済に含めていない。"
                     "金融機関が応じなければ、その額がただちに不足する")
    simple = ordinary - ctx + dep
    free = simple - debt
    basis = [f"手元資金＝現金預金 {cash:,}（{src('cash')}）",
             f"簡易営業CF＝経常利益 {ordinary:,}（{src('ord')}）−法人税等 {ctx:,}＋減価償却費 {dep:,}＝{simple:,}",
             f"約定返済＝{debt:,}　返済後収支＝{free:,}"] + basis + ["設備投資は含めていない（楽観側）"]
    return CashBase(liquid_funds=cash, simple_cf=simple, debt_service=debt, free_cf=free,
                    required_cf=max(0, -free), basis=basis, missing=missing)


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
    if net >= 0:
        return None
    return HORIZON_MONTHS + cash / -net


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
