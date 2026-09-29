"""財務・4P突合マトリクスに出す指標の定義と計算（決定論）。

どの指標も「計算式」「分子と分母の内訳（科目・金額・出典頁）」「前期→当期」を持つ。画面はここだけを読み、
数字の出どころを常に示す。会社ごとに意味のある指標だけを出す（受取配当依存は受取配当金のある会社だけ、など）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from core import metrics
from schema import Financials

DEBT_KEYS = ("stl", "cltd", "ltd", "cbond", "bond", "cls", "lls")


@dataclass(frozen=True)
class Indicator:
    key: str
    label: str
    unit: Literal["amount", "ratio"]
    formula: str
    num: tuple[str, ...]
    den: tuple[str, ...] = ()
    when: Callable[[Financials], bool] | None = None   # 会社によって意味がある場合だけ出す
    real_bs: bool = False                               # 実質本業BSで値が変わる（総資産・自己資本比率・ROA）
    why: str = ""                                       # なぜ見るのか（画面の説明）
    chart: bool = True                                  # 比率の横棒グラフに載せる（100%を超える比率は表だけ）


@dataclass
class Part:
    key: str
    label: str
    cur: int | None
    prev: int | None
    source: str


@dataclass
class Value:
    ind: Indicator
    cur: float | None
    prev: float | None
    num: list[Part] = field(default_factory=list)
    den: list[Part] = field(default_factory=list)
    note: str = ""

    @property
    def basis(self) -> str:
        """「分子 ÷ 分母」の内訳を1行で（出典頁付き）。"""
        def side(parts):
            return "＋".join(f"{p.label} {p.cur:,}（{p.source}）" for p in parts if p.cur is not None) or "—"
        return side(self.num) + ("" if not self.den else " ÷ " + side(self.den))


def _v(fin: Financials, key: str, period: str = "cur") -> int | None:
    return fin.value(key, period)


def _has(fin: Financials, key: str) -> bool:
    return bool(_v(fin, key))


COMMON: tuple[Indicator, ...] = (
    Indicator("sales", "売上高", "amount", "売上高", ("sales",), why="事業の規模"),
    Indicator("op_margin", "営業利益率", "ratio", "営業利益 ÷ 売上高", ("op",), ("sales",), why="本業の稼ぐ力"),
    Indicator("ta", "総資産", "amount", "資産合計", ("ta",), real_bs=True, why="事業に使っている資産の大きさ"),
    Indicator("equity_ratio", "自己資本比率", "ratio", "純資産 ÷ 総資産", ("tna",), ("ta",), real_bs=True,
              why="返さなくてよい資金の厚み（倒れにくさ）"),
    Indicator("debt", "有利子負債", "amount", "短期・長期借入金＋社債＋リース債務", DEBT_KEYS, why="利息と返済の重さ"),
    Indicator("cash", "手許現預金", "amount", "現金預金", ("cash",), why="当面の支払い余力"),
    Indicator("roa", "営業利益ROA", "ratio", "営業利益 ÷ 総資産", ("op",), ("ta",), real_bs=True,
              why="資産を本業でどれだけ生かしているか"),
)
CONDITIONAL: tuple[Indicator, ...] = (
    Indicator("div_dep", "経常利益に占める受取配当金", "ratio", "受取配当金 ÷ 経常利益", ("div",), ("ord",),
              when=lambda f: _has(f, "div") and (_v(f, "ord") or 0) > 0, why="本業以外の収益への依存"),
    Indicator("purchase_ratio", "商品仕入高比率", "ratio", "当期商品仕入高 ÷ 売上高", ("pur",), ("sales",),
              when=lambda f: _has(f, "pur"), why="自社製造でない商品の比重"),
)
RATIOS: tuple[Indicator, ...] = (   # 比率の突合（同業平均・ベンチマークと並べるもの）
    Indicator("op_margin", "営業利益率", "ratio", "営業利益 ÷ 売上高", ("op",), ("sales",)),
    Indicator("sga_ratio", "販管費率", "ratio", "（販売費＋一般管理費） ÷ 売上高", ("sell", "adm"), ("sales",)),
    Indicator("mat_ratio", "材料費比率（製造費用に占める）", "ratio", "材料費 ÷ 当期総製造費用", ("mat",), ("tmc",)),
    Indicator("purchase_ratio", "商品仕入高比率（売上高に占める）", "ratio", "当期商品仕入高 ÷ 売上高", ("pur",), ("sales",)),
    Indicator("equity_ratio", "自己資本比率", "ratio", "純資産 ÷ 総資産", ("tna",), ("ta",), real_bs=True),
    Indicator("div_dep", "経常利益に占める受取配当金", "ratio", "受取配当金 ÷ 経常利益", ("div",), ("ord",)),
    Indicator("current_ratio", "流動比率", "ratio", "流動資産 ÷ 流動負債", ("tca",), ("tcl",), chart=False),
)


def kpis(fin: Financials) -> list[Indicator]:
    """この会社で見る指標：全社共通のものと、条件を満たすときだけの会社固有のもの。"""
    return list(COMMON) + [i for i in CONDITIONAL if i.when is None or i.when(fin)]


def _parts(fin: Financials, keys: tuple[str, ...]) -> list[Part]:
    out = []
    for k in keys:
        it = fin.items.get(k)
        if it is None or (it.cur is None and it.prev is None):
            continue
        src = f"{it.source.file} p.{it.source.page}" if it.source.page else (it.source.file or "出典なし")
        out.append(Part(k, it.label, it.cur, it.prev, src))
    return out


def _sum(parts: list[Part], period: str) -> int | None:
    vals = [getattr(p, period) for p in parts]
    if not vals or any(v is None for v in vals):
        return None
    return sum(vals)


def evaluate(fin: Financials, ind: Indicator, mode: str = "nominal", extra=()) -> Value:
    num, den = _parts(fin, ind.num), _parts(fin, ind.den)
    if ind.real_bs and mode == "real":
        try:
            bs = metrics.balance_sheet(fin, "real", extra)
        except ValueError as e:
            return Value(ind, None, None, num, den, note=str(e))
        cur = {"ta": bs["総資産"], "equity_ratio": bs["自己資本比率"], "roa": bs["営業利益ROA"]}[ind.key]
        return Value(ind, cur, None, num, den, note="実質BS：" + bs["注記"])

    def calc(period):
        n = _sum(num, period)
        if not ind.den:
            return n
        d = _sum(den, period)
        return None if n is None or not d else n / d

    return Value(ind, calc("cur"), calc("prev"), num, den)


def fmt(ind: Indicator, v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v / 100_000:,.1f}億円" if ind.unit == "amount" else f"{v:.1%}"


def delta_text(val: Value) -> str | None:
    """前期からの動き。金額は増減率、比率はポイント差。符号を先頭に置く（画面の矢印の向きになる）。"""
    if val.cur is None or val.prev is None:
        return None
    if val.ind.unit == "amount":
        if not val.prev:
            return None
        return f"{val.cur / val.prev - 1:+.1%}（前期比）"
    pt = round((val.cur - val.prev) * 100, 1)
    return "±0.0pt（前期比）" if pt == 0 else f"{pt:+.1f}pt（前期比）"
