"""反論（攻撃）による提案の見直し：差し戻しと減額採択（決定論。LLM は使わない）。

Growth の提案が形式審査と中身の審理を通っても、Dr. Rebuild が実現性への疑義（例：労務費の過大なカット）を
出典と決着条件つきで示し、その攻撃が審査を通ったなら、提案の資金効果を機械的に全額数えることはしない。

- 攻撃が「現実的な資金効果」（feasible_cf）を示す → 減額採択：疑義を向けた科目の資金効果をその額まで減らして数える
- 攻撃が 0 を示す、または額を示さない → 差し戻し：その提案は数えない
- Growth の防御（防御の相手＝その攻撃）が審査を通れば、攻撃は効かなくなり、提案は元の額に戻る

判定は書き換えず、見直しの判定（Ruling.by="challenge"）を積み上げる（最新の判定が効く）。
"""

from __future__ import annotations

from schema import CausalBridge, DebateMessage, Ruling

PROPOSERS = ("growth", "rebuild")


def _latest(rulings: list[Ruling]) -> dict[str, Ruling]:
    out: dict[str, Ruling] = {}
    for r in rulings:
        out[r.message_id] = r
    return out


def _latest_review(rulings: list[Ruling]) -> dict[str, Ruling]:
    return _latest([r for r in rulings if r.by == "review"])


def _reduce(b: CausalBridge, feasible: int) -> CausalBridge:
    """資金効果を feasible まで減らす（増やすことはしない）。科目の変動額も同じ割合で縮める。"""
    if abs(b.cf_effect) <= feasible:
        return b
    ratio = feasible / abs(b.cf_effect)
    sign = 1 if b.cf_effect > 0 else -1
    return b.model_copy(update={"cf_effect": sign * feasible, "amount": max(1, round(b.amount * ratio)),
                                "rationale": (b.rationale + "　" if b.rationale else "") + "（反論を受けて減額）"})


def effective_attacks(messages: list[DebateMessage], rulings: list[Ruling]) -> dict[str, list[DebateMessage]]:
    """提案ごとの、効いている攻撃（審査を通り、審査を通った防御で打ち消されていないもの）。"""
    review = _latest_review(rulings)
    by_id = {m.id: m for m in messages}
    passed = {mid for mid, r in review.items() if r.verdict == "通過"}
    countered = {m.target_message for m in messages
                 if m.action == "防御" and m.id in passed and m.target_message in by_id
                 and by_id[m.target_message].action == "攻撃"}
    out: dict[str, list[DebateMessage]] = {}
    for m in messages:
        if (m.speaker == "rebuild" and m.action == "攻撃" and m.id in passed and m.target_message
                and m.id not in countered):
            t = by_id.get(m.target_message)
            if t is not None and t.action == "提案" and t.speaker in PROPOSERS and t.bridges:
                out.setdefault(t.id, []).append(m)
    return out


def _desired(proposal: DebateMessage, attacks: list[DebateMessage]) -> tuple[str, list[CausalBridge] | None, list[str]]:
    """反論を反映した判定（verdict、数える因果ブリッジ、理由）。"""
    bridges = list(proposal.bridges)
    reasons: list[str] = []
    for a in attacks:
        accounts = {b.account for b in bridges}
        scope = a.challenged_account if a.challenged_account in accounts else None
        what = f"「{scope}」" if scope else "提案全体"
        if a.feasible_cf is None or a.feasible_cf <= 0:
            return "差し戻し", None, [f"{a.id} の反論（実現性の疑義）が審査を通ったため、{what}の資金効果を数えません。"
                                      "防御で反論に答えるか、数字を改めて出し直してください"]
        if scope:
            bridges = [_reduce(b, a.feasible_cf) if b.account == scope else b for b in bridges]
        else:   # 提案全体で feasible_cf まで：資金を生む橋の合計を按分して縮める
            pos = sum(b.cf_effect for b in bridges if b.cf_effect > 0)
            if pos > a.feasible_cf:
                ratio = a.feasible_cf / pos
                bridges = [_reduce(b, int(b.cf_effect * ratio)) if b.cf_effect > 0 else b for b in bridges]
        reasons.append(f"{a.id} の反論（実現性の疑義）が審査を通ったため、{what}の資金効果を{a.feasible_cf:,}千円（年）までに減額して数えます")
    if [b.cf_effect for b in bridges] == [b.cf_effect for b in proposal.bridges]:
        return "通過", None, []   # 反論の額が提案を下回らない：元のまま
    return "通過", bridges, ["減額採択：" + "／".join(reasons)]


def challenge_rulings(messages: list[DebateMessage], rulings: list[Ruling], round_no: int) -> list[Ruling]:
    """審査を通った攻撃・防御を反映した見直しの判定（変わるものだけ）。"""
    review = _latest_review(rulings)
    latest = _latest(rulings)
    attacks = effective_attacks(messages, rulings)
    out: list[Ruling] = []
    for m in messages:
        if m.action != "提案" or m.speaker not in PROPOSERS or not m.bridges:
            continue
        base = review.get(m.id)
        if base is None or base.verdict != "通過":   # 提案そのものが審査を通っていなければ、反論を待つまでもない
            continue
        verdict, adjusted, reasons = _desired(m, attacks.get(m.id, []))
        cur = latest.get(m.id)
        cur_adj = None if cur is None else cur.adjusted_bridges
        if cur is not None and cur.verdict == verdict and cur_adj == adjusted:
            continue
        if not reasons:
            reasons = ["反論が防御で打ち消されたため、元の資金効果で数えます"]
        out.append(Ruling(message_id=m.id, round=round_no, verdict=verdict, reasons=reasons, by="challenge",
                          adjusted_bridges=adjusted))
    return out
