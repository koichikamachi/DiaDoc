"""議論ログのCSVエクスポート（実務で Excel 加工や報告書作成に使う）。

1行＝1発言。因果ブリッジが複数ある発言は、ブリッジごとに1行（発言の本文は各行に繰り返す）。
残余月数と回収CF累計は「その発言の時点で分かっていた値」＝直前の Judge の裁定時点（裁定前は改善前の値）。
日本語の Excel で文字化けしないよう、BOM 付き UTF-8（utf-8-sig）で書く。
"""

from __future__ import annotations

import csv
import io

COLUMNS = ("round", "step", "speaker", "message", "proposal_action", "target_account", "amount_thousand",
           "lead_time_months", "judgement", "cash_runway", "accumulated_cf", "timestamp")

SPEAKER_NAMES = {"radar": "Analyst Radar", "growth": "Prof. Growth", "rebuild": "Dr. Rebuild",
                 "judge": "Moderator Judge", "human": "ライム（人間介入）"}


def _runway(v: float | None, pending: bool = False) -> str:
    if v is None:
        return "判定保留（約定返済が未確認）" if pending else "資金流出なし"
    return f"{v:.1f}"


def rows(state) -> list[dict]:
    from tools.standard_accounts import LABELS

    if state is None:
        return []
    verdict: dict[str, str] = {}
    for r in state.rulings:
        verdict[r.message_id] = r.verdict
    runway = state.monitor.base_runway_months
    pending = state.monitor.base.shortage_pending
    acc = 0
    out: list[dict] = []
    for step, m in enumerate(state.messages, 1):
        if m.speaker == "judge" and m.judge_note is not None:
            runway, acc = m.judge_note.runway, m.judge_note.accumulated
            pending = bool(m.judge_note.pending) or pending
            d = m.judge_note.decision
            t = m.judge_note.tally
            judgement = (f"通過{t.get('通過', 0)}・差し戻し{t.get('差し戻し', 0)}・退け{t.get('退け', 0)}"
                         + (f"／フェーズ判定 {d.current}→{d.next}（{d.rule}）" if d and d.changed else ""))
        elif m.action == "比較":
            judgement = "／".join(f"{a.name}：{a.months_needed}か月" + ("" if a.in_time is None else
                                  ("（残余月数内）" if a.in_time else "（残余月数を超える）")) for a in m.comparison)
        else:
            judgement = verdict.get(m.id, "")
        base = {"round": m.round, "step": step, "speaker": SPEAKER_NAMES.get(m.speaker, m.speaker),
                "message": m.text, "proposal_action": m.action, "judgement": judgement,
                "cash_runway": _runway(runway, pending), "accumulated_cf": acc, "timestamp": m.at}
        if m.bridges:
            for b in m.bridges:
                out.append(base | {"target_account": f"{LABELS.get(b.account, b.account)}（{b.direction}）",
                                   "amount_thousand": b.cf_effect,
                                   "lead_time_months": b.lead_months})
        else:
            out.append(base | {"target_account": "", "amount_thousand": "", "lead_time_months": ""})
    return out


def to_csv_bytes(state) -> bytes:
    """議論ログを CSV（utf-8-sig、改行 CRLF）のバイト列にする。"""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\r\n")
    w.writeheader()
    for r in rows(state):
        w.writerow({k: r.get(k, "") for k in COLUMNS})
    return buf.getvalue().encode("utf-8-sig")
