"""診断適格性（Diagnostic Data Fitness：DDF）。読み取った財務データを、診断に使ってよいかの三区分で判定する。

監査の重要性の考え方を、診断の用途に置き換えたもの（決定論。LLM は使わない）。

- 適格（Fit）：不一致なし。または差が端数処理の許容差（内訳の件数×1単位）の内にある。監査でいう「明らかに僅少」に近い
- 条件付き適格（Conditionally Fit）：許容差を超えるが、診断重要性（DM：総資産・売上高の0.5%未満、かつ1,000千円未満）の範囲内で、
  質的重要性にも抵触しない差。原因の分からない差（未解明差異）として、人が承認したときだけ使う
- 不適格（Not Fit）：DM 以上の差、質的重要性に抵触する差、または中心の検算が確かめられないもの。論争を始めない

質的重要性（金額が小さくても不適格にするもの）は、「どちらの数字を信じるかで診断の結論が変わる」差である。
内訳から計算した値と書類に書かれた値のどちらが正しいかは分からないので、両方で結論を比べる。
  1. 営業損益の符号が変わる（黒字と赤字が入れ替わる）
  2. 純資産の符号が変わる（帳簿上の債務超過の有無が入れ替わる。含み損益を入れた実質の債務超過はここでは見ない）
  3. 資金不足の有無が変わる（返済後の資金収支の過不足が入れ替わる。トリアージに入るかどうかが変わる）
"""

from __future__ import annotations

FIT = "適格（Fit）"
COND = "条件付き適格（Conditionally Fit）"
NOT_FIT = "不適格（Not Fit）"

# 差（計算値−報告値）が「内訳のほうが正しい」とした場合に、営業利益をどちら向きに動かすか
OP_EFFECT = {"販管費合計": -1, "売上原価（調整表）": -1, "当期総製造費用": -1, "当期製品製造原価": -1,
             "売上総利益": 1, "営業利益": 1}
# 同じく純資産（資産−負債）をどちら向きに動かすか
EQ_EFFECT = {"流動資産合計": 1, "有形固定資産合計": 1, "無形固定資産合計": 1, "投資その他の資産合計": 1, "固定資産合計": 1,
             "資産合計": 1, "流動負債合計": -1, "固定負債合計": -1, "負債合計": -1,
             "利益剰余金合計": 1, "株主資本合計": 1, "純資産合計": 1,
             "資産合計＝負債純資産合計": 1, "負債合計＋純資産合計＝負債純資産合計": -1}


def _deltas(failures, effect: dict[str, int]) -> list[int]:
    """一つずつ内訳を正とした場合と、すべてを正とした場合の、動く額の候補。"""
    each = [effect[f.check] * f.diff for f in failures if f.period == "cur" and f.check in effect]
    return each + ([sum(each)] if len(each) > 1 else [])


def _flips(base: int, deltas: list[int], negative) -> int | None:
    """符号（negative の判定）が入れ替わる候補があれば、その値を返す。"""
    for d in deltas:
        alt = base + d
        if negative(alt) != negative(base):
            return alt
    return None


def qualitative(fin, failures) -> list[str]:
    """質的重要性に抵触する理由（なければ空）。failures は core.materiality.Failure の一覧。"""
    from core import metrics

    out: list[str] = []
    op_d = _deltas(failures, OP_EFFECT)
    op = fin.value("op")
    if op is not None and op_d:
        alt = _flips(op, op_d, lambda v: v < 0)
        if alt is not None:
            out.append(f"営業損益の符号が変わる：書類の営業利益 {op:,} ／ 内訳を正とすると {alt:,}（黒字と赤字が入れ替わる）")
    tna = fin.value("tna")
    eq_d = _deltas(failures, EQ_EFFECT)
    if tna is not None and eq_d:
        alt = _flips(tna, eq_d, lambda v: v < 0)
        if alt is not None:
            out.append(f"純資産の符号が変わる：書類の純資産 {tna:,} ／ 内訳を正とすると {alt:,}（帳簿上の債務超過の有無が入れ替わる）")
    if op_d:
        base = metrics.cash_base(fin)
        if base.free_cf is not None:   # 営業利益の差はそのまま経常利益・簡易営業CFを動かす
            alt = _flips(base.free_cf, op_d, lambda v: v < 0)
            if alt is not None:
                out.append(f"資金不足の有無が変わる：書類どおりなら返済後の資金収支 {base.free_cf:,}（年）／ "
                           f"内訳を正とすると {alt:,}（トリアージに入るかどうかが変わる）")
    return out


# 検算ゲートの内部の判定 → 画面に出す DDF の区分
GATE_LABEL = {
    "通過": FIT,
    "通過（端数調整）": f"{COND}：未解明差異を承認済み",
    "軽微": f"{COND}：承認待ち",
    "差し替え待ち": "差し替え待ち（この資料は採用しない）",
    "停止": NOT_FIT,
    "未確認": NOT_FIT,
    "対象外": "対象外（財務諸表一式ではない部分資料）",
}


def gate_label(gate: str | None) -> str:
    return GATE_LABEL.get(gate or "", gate or "—")


def run_status(run) -> str:
    """回次の財務データの診断適格性（レポートの冒頭に書く一行）。"""
    import json

    from core.guardrails import core_unverified, reconcile

    fin = run.financials()
    if fin is None:
        d = run.path / "extracted"
        gates = []
        for f in sorted(d.glob("*.json")) if d.exists() else []:
            try:
                gates.append(json.loads(f.read_text(encoding="utf-8")).get("gate"))
            except (OSError, ValueError):
                continue
        if any(g in ("停止", "未確認") for g in gates):
            return f"{NOT_FIT}（財務データは採用していません）"
        if "軽微" in gates:
            return f"{COND}：承認待ち（財務データは未採用）"
        return "未判定（財務データがまだありません）"
    if fin.rounding_adjustments:
        total = sum(abs(a.amount) for a in fin.rounding_adjustments)
        return f"{COND}：未解明差異 {total:,}{fin.unit}を承認済み"
    rec = reconcile(fin)
    if not rec.passed or core_unverified(rec):
        return NOT_FIT
    return FIT
