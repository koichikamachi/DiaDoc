"""検算ゲートの二段階判定（重要性）と、人が承認する端数調整。

検算で合わなかった項目の差額（絶対値の合計）が、次の三つをすべて満たすときだけ「軽微な差異」とする。
  - 総資産の 0.5% 未満
  - 売上高の 0.5% 未満
  - 100万円（1,000千円）未満
それ以外は「重大な差異」とし、診断を止める。軽微な差異は、人が「端数調整で続行」を選んだときだけ、
差額を端数調整差額として記録して先へ進める（書類に書かれた合計は正として残し、指標もそれを使う）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schema import Financials, ReconciliationReport, RoundingAdjustment

RATE = 0.005                 # 総資産・売上高に対する割合の上限（0.5%）
ABS_LIMIT_THOUSAND = 1_000   # 金額の上限（千円）＝100万円
TO_THOUSAND = {"千円": 1.0, "円": 0.001, "百万円": 1_000.0}

# 資産側の検算（差額はその他流動資産に計上）
ASSET_CHECKS = {"流動資産合計", "有形固定資産合計", "無形固定資産合計", "投資その他の資産合計", "固定資産合計", "資産合計",
                "総資産額"}
BS_GROUPS = {"BS内訳", "貸借一致"}


@dataclass
class Failure:
    group: str
    check: str
    period: str
    computed: int
    reported: int
    diff: int                # 計算値 − 報告値

    @property
    def amount(self) -> int:
        """計算値にこれを足すと報告値になる額。"""
        return -self.diff


@dataclass
class Materiality:
    level: str                               # 軽微 / 重大
    total_diff: int                          # 差額の絶対値の合計（書類の表示単位）
    total_diff_thousand: float
    pct_assets: float | None
    pct_sales: float | None
    failures: list[Failure] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def headline(self) -> str:
        pct = "—" if self.pct_assets is None else f"{self.pct_assets:.3%}"
        return f"差額: {self.total_diff_thousand:,.0f}千円、総資産の{pct}"


def failures(rec: ReconciliationReport) -> list[Failure]:
    out = []
    for c in rec.checks:
        for p in c.periods:
            if p.status == "不一致" and p.computed is not None and p.reported is not None:
                out.append(Failure(c.group, c.name, p.period, p.computed, p.reported, p.diff))
    return out


def _base(fin: Financials, key: str) -> int | None:
    v = fin.value(key, "cur")
    return v if v else fin.value(key, "prev")


def assess(fin: Financials, rec: ReconciliationReport) -> Materiality | None:
    """不一致があれば、軽微か重大かを判定する（不一致がなければ None）。"""
    fs = failures(rec)
    if not fs:
        return None
    scale = TO_THOUSAND.get(fin.unit or "千円")
    total = sum(abs(f.diff) for f in fs)
    ta, sales = _base(fin, "ta"), _base(fin, "sales")
    reasons = []
    if scale is None:
        reasons.append(f"表示単位（{fin.unit}）を千円に換算できない")
        scale = 1.0
    thousand = total * scale
    pa = total / ta if ta else None
    ps = total / sales if sales else None
    if pa is None or ps is None:
        reasons.append("総資産または売上高が読み取れず、割合を判定できない")
    else:
        if pa >= RATE:
            reasons.append(f"総資産の{pa:.3%}（0.5%以上）")
        if ps >= RATE:
            reasons.append(f"売上高の{ps:.3%}（0.5%以上）")
    if thousand >= ABS_LIMIT_THOUSAND:
        reasons.append(f"差額{thousand:,.0f}千円（100万円以上）")
    return Materiality("重大" if reasons else "軽微", total, thousand, pa, ps, fs, reasons)


def booked_to(f: Failure) -> str:
    """端数調整差額の計上先。BS は資産側ならその他流動資産、負債・純資産側ならその他流動負債。PL は雑損益。"""
    if f.group in BS_GROUPS or f.check in ("純資産額", "総資産額"):
        if f.group == "貸借一致":
            # 計算値（資産または負債＋純資産）が報告値より小さい＝その側が不足
            return "その他流動資産（端数調整差額）" if (f.check.startswith("資産合計") and f.amount > 0) \
                else "その他流動負債（端数調整差額）"
        return "その他流動資産（端数調整差額）" if f.check in ASSET_CHECKS else "その他流動負債（端数調整差額）"
    return "雑損益（端数調整）"


def adjustments(m: Materiality, approved_at: str, file: str = "") -> list[RoundingAdjustment]:
    return [RoundingAdjustment(group=f.group, check=f.check, period=f.period, amount=f.amount,
                               booked_to=booked_to(f), approved_at=approved_at, file=file) for f in m.failures]
