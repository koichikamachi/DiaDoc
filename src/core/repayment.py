"""約定返済額の確定（人間が返済予定表を見て、年間の約定返済額を入れる）。回次ごとの repayment.json。

決算書に1年内返済の区分がなく約定返済が確かめられないとき（BS記載に疑問あり）、資金不足の有無は判定保留になる。
返済予定表（金銭消費貸借契約書）を確かめた人が、年間の約定返済額と根拠を入れると、資金の監視はその額で計算し直し、
判定保留は解け、Analyst Radar の宿題「借入金返済予定表」は解消になる。

CLAUDE.md 6.6 の例外「外部証拠に基づく人間の確定判断（監査的オーバーライド）」の適用。書類から確かめられない数字を、
外部証拠（返済予定表など）を確かめた人が根拠つきで確定するときだけ使い、根拠のない入力は受け付けない。入力と取り消しは監査証跡と論争のタイムラインに残す。
決算書の値は書き換えない（6.9）。確定した額は資金の監視の計算にだけ使う。

保存と引き継ぎは実質化の調整（core.adjust）と同じ：財務データが同じ範囲の子の回次は引き継ぎ、最新の入力が効く。
"""

from __future__ import annotations

from pydantic import BaseModel

from schema import MAX_AMOUNT, stamp

FILE = "repayment.json"
ACTOR = "支援担当者"


class Repayment(BaseModel):
    amount: int                  # 年間の約定返済額（千円）。長期借入金・社債・リース債務の1年分の合計
    basis: str                   # 根拠（例：〇〇銀行の返済予定表を確認）
    at: str
    run_id: str = ""
    message_id: str | None = None   # 論争に書き込んだ介入の発言ID

    def describe(self) -> str:
        return f"年間約定返済額 {self.amount:,}千円（根拠：{self.basis}）"


def load(run) -> Repayment | None:
    """この回次で効いている確定額（なければ None）。自分の回次になければ、財務データが同じ範囲の親をさかのぼる。"""
    from core.adjust import _chain

    for r in _chain(run):
        own = r.read(FILE, [])
        if own:
            last = own[-1]
            return None if last.get("removed") else Repayment.model_validate(last)
    return None


def cash_base_for(run, fin=None):
    """回次の資金の基礎値（確定した約定返済があれば、それで計算する）。"""
    from core.metrics import cash_base

    fin = fin if fin is not None else run.financials()
    return None if fin is None else cash_base(fin, load(run))


def confirm(run, amount: int, basis: str) -> Repayment:
    run._guard()
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise ValueError("年間約定返済額は千円単位の整数で入れてください") from None
    if amount < 0:
        raise ValueError("年間約定返済額は0以上で入れてください")
    if amount > MAX_AMOUNT:
        raise ValueError("年間約定返済額が大きすぎます（千円単位・9桁以内）")
    basis = (basis or "").strip()
    if not basis:
        raise ValueError("根拠を書いてください（例：〇〇銀行の返済予定表を確認）。根拠のない数字は入れません")
    rec = Repayment(amount=amount, basis=basis, at=stamp(), run_id=run.run_id)
    run.write(FILE, run.read(FILE, []) + [rec.model_dump()])
    _audit(run, f"約定返済額の確定（年間 {amount:,}千円）", [f"根拠：{basis}"])
    return rec


def withdraw(run) -> Repayment | None:
    """この回次で入れた確定を取り消す（記録は消さず、取り消しを積む）。"""
    run._guard()
    cur = load(run)
    if cur is None or cur.run_id != run.run_id:
        return None
    run.write(FILE, run.read(FILE, []) + [{"removed": True, "at": stamp(), "run_id": run.run_id}])
    _audit(run, f"約定返済額の確定を取り消し（年間 {cur.amount:,}千円）", [])
    return cur


def set_message_id(run, message_id: str) -> None:
    own = run.read(FILE, [])
    if own and not own[-1].get("removed"):
        own[-1]["message_id"] = message_id
        run.write(FILE, own)


def _audit(run, action: str, entries: list[str]) -> None:
    run.write("audit_log.json", run.read("audit_log.json", []) + [
        {"at": stamp(), "actor": ACTOR, "action": action, "entries": entries}])


def intervention_text(rec: Repayment, removed: bool = False) -> str:
    if removed:
        return (f"約定返済額の確定を取り消します：{rec.describe()}。"
                "約定返済は再び「BS記載に疑問あり、確認が必要」として扱ってください。")
    return (f"約定返済額を確定します：{rec.describe()}。以後、資金の監視はこの返済額で計算してください"
            "（判定保留を解除します。決算書の数字は変えません）。")
