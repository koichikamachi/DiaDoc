"""実質化の調整の保存と読み出し（回次ごとの adjustments.json）。

調整は財務データと同じ回次に属する。決算書を差し替えて新しい回次を開いたら、古い調整は引き継がない
（帳簿の額が変わるので、前提も変わる）。定性資料だけを足した子の回次では、親の調整を引き継ぐ。
"""

from __future__ import annotations

from schema import ASSET_BLOCKS, LIABILITY_BLOCKS, Adjustment, stamp

FILE = "adjustments.json"
BLOCKS = ASSET_BLOCKS + LIABILITY_BLOCKS


def _chain(run):
    """この回次から、財務データを持つ回次までをさかのぼる（財務データが同じ範囲）。"""
    src = run.financials_source()
    r, out = run, []
    while r is not None:
        out.append(r)
        if src is None or r.run_id == src.run_id:
            break
        r = r.parent()
    return out


def load(run) -> list[Adjustment]:
    out: list[Adjustment] = []
    for r in reversed(_chain(run)):
        out += [Adjustment.model_validate(a) for a in r.read(FILE, [])]
    return out


def add(run, account: str, block: str, amount: int, note: str = "", key: str | None = None,
        message_id: str | None = None) -> Adjustment:
    if block not in BLOCKS:
        raise ValueError(f"区画は {BLOCKS} のどれかです")
    if not amount:
        raise ValueError("調整額が0です")
    if not (account or "").strip():
        raise ValueError("科目名が空です")
    own = run.read(FILE, [])
    used = {a.id for a in load(run)}
    n = 1
    while f"A{n}" in used:
        n += 1
    adj = Adjustment(id=f"A{n}", account=account.strip(), key=key, block=block, amount=int(amount),
                     note=(note or "").strip(), at=stamp(), message_id=message_id)
    run.write(FILE, own + [adj.model_dump()])
    return adj


def remove(run, adj_id: str) -> Adjustment | None:
    """この回次で入力した調整だけを取り消せる（親の回次の調整は親で取り消す）。"""
    own = [Adjustment.model_validate(a) for a in run.read(FILE, [])]
    hit = next((a for a in own if a.id == adj_id), None)
    if hit is not None:
        run.write(FILE, [a.model_dump() for a in own if a.id != adj_id])
    return hit


def set_message_id(run, adj_id: str, message_id: str) -> None:
    own = run.read(FILE, [])
    for a in own:
        if a["id"] == adj_id:
            a["message_id"] = message_id
    run.write(FILE, own)


def intervention_text(adj: Adjustment, removed: bool = False) -> str:
    if removed:
        return f"実質化の調整を取り消します：{adj.describe()}"
    return (f"実質化の調整を入れます：{adj.describe()}。"
            "以後、実質の貸借対照表はこの調整を前提にしてください（資金の計算は変わりません）。")
