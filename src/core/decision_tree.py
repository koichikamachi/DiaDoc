"""論争の状態から意思決定ツリーを組み立てる（決定論。描画は ui.components.tree）。

根＝診断ミッション。その下に改善の4レバー、各レバーの下に Growth・Rebuild の提案（審査と資金の時間軸で見た採否）。
Rebuild のトリアージ宣告が審査を通ると「Level 0 の道」の枝が生え、Judge の比較（道筋がつくか）と、
人間が記録した採択が重なる。論争が一手進むたびに作り直すので、ツリーは論争とともに育つ。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core import digest
from core.guardrails import LEVERS, lever_of

PHASE_LABEL = {"exploration": "探索", "triage_ready": "トリアージ", "settlement": "決着"}
SPEAKER = {"growth": "Prof. Growth", "rebuild": "Dr. Rebuild"}


@dataclass
class TreeNode:
    id: str
    parents: list[str]    # 複数のレバーにまたがる提案は、それぞれのレバーから枝が伸びる（木ではなくDAG）
    kind: str          # root / premise / lever / proposal / triage / option
    label: str
    status: str        # 表示の状態（配色の鍵）
    detail: list[str] = field(default_factory=list)


def _levers(p: digest.ProposalStatus) -> list[str]:
    """提案が触れるレバー（ブリッジの科目から決定論で決める。4レバーの順）。"""
    touched = {lever_of(b.account) for b in p.bridges}
    return [lv for lv in LEVERS if lv in touched]


def _bridge_line(p: digest.ProposalStatus) -> str:
    cash = sum(b.cf_effect for b in p.bridges)
    lead = min((b.lead_months for b in p.bridges), default=None)
    if not p.bridges:
        return "因果ブリッジなし"
    return f"資金 {cash:+,}千円" + (f"・{lead}か月後から" if lead is not None else "")


def build(state, mission: str | None = None) -> list[TreeNode]:
    """DebateState からツリーの節を作る。state が None（論争前）なら根とレバーだけ。"""
    mission = state.mission if state else (mission or "（診断ミッション未設定）")
    where = f"第{state.round}ラウンド・{PHASE_LABEL.get(state.phase, state.phase)}" if state else "開始前"
    nodes = [TreeNode("root", [], "root", mission, "root", [where])]
    if state is None:
        return nodes + [TreeNode(f"L{i + 1}", ["root"], "lever", lv, "未着手") for i, lv in enumerate(LEVERS)]

    # 採択の記録（「採択：」で始まる人間の発言）は前提ではなく結論なので、道の枝の側に出す
    humans = [m for m in state.messages if m.speaker == "human" and not m.text.startswith("採択：")]
    if humans:
        nodes.append(TreeNode("H", ["root"], "premise", "人間が置いた前提", "前提",
                              [f"{m.id}：{m.text[:30]}{'…' if len(m.text) > 30 else ''}" for m in humans[-3:]]
                              + ([f"ほか{len(humans) - 3}件"] if len(humans) > 3 else [])))

    props = digest.proposals(state)
    by_lever: dict[str, list[digest.ProposalStatus]] = {}
    for p in props:
        for lv in _levers(p):
            by_lever.setdefault(lv, []).append(p)
    for i, lv in enumerate(LEVERS):
        mine = by_lever.get(lv, [])
        if not mine:
            status = "未着手"
        elif any(p.status in ("審査通過・時期内", "一部のみ間に合う", "審査通過・時期外", "減額採択") for p in mine):
            status = "通過あり"
        elif any(p.status == "審理中" for p in mine):
            status = "審理中"
        else:
            status = "棄却のみ"
        nodes.append(TreeNode(f"L{i + 1}", ["root"], "lever", lv, status, [f"提案 {len(mine)}件"] if mine else []))
    lever_id = {lv: f"L{i + 1}" for i, lv in enumerate(LEVERS)}
    for p in props:
        nodes.append(_proposal(p, [lever_id[lv] for lv in _levers(p)] or ["root"]))

    tri = digest.triage(state)
    if tri is None and state.phase == "triage_ready":
        nodes.append(TreeNode("T", ["root"], "triage", "トリアージ（Level 0 の道）", "審理中",
                              ["4レバーを試しても資金の不足が埋まらないため、Rebuild の宣告を待っている"]))
    elif tri is not None:
        cmp_ = digest.comparison(state)
        assess = {a.name: a for a in (cmp_.comparison if cmp_ else [])}
        nodes.append(TreeNode("T", ["root"], "triage", "トリアージ（Level 0 の道）", "宣告",
                              [f"Dr. Rebuild の宣告（{tri.message_id}・第{tri.round}ラウンド）",
                               "Judge の比較済み" if cmp_ else "Judge の比較待ち"]))
        for j, o in enumerate(tri.options):
            a = assess.get(o.name)
            detail = []
            if o.keep:
                detail.append("残す：" + "・".join(o.keep))
            if o.discard:
                detail.append("捨てる：" + "・".join(o.discard))
            if a is not None:
                months = f"{a.months_needed}か月" if a.months_needed is not None else "不明"
                mark = {True: "✓ 資金が尽きる前", False: "✕ 資金が尽きた後"}.get(a.in_time, "判定なし")
                detail.append(f"道筋がつくまで {months}　{mark}")
            if state.adopted_option:
                status = "採択" if o.name == state.adopted_option else "不採択"
            elif a is None:
                status = "比較待ち"
            else:
                status = {True: "時期内", False: "時期外"}.get(a.in_time, "比較済み")
            if status == "採択" and state.adopted_note:
                detail.append("理由・条件：" + state.adopted_note)
            nodes.append(TreeNode(f"O{j + 1}", ["T"], "option", o.name, status, detail))
    return nodes


def _proposal(p: digest.ProposalStatus, parents: list[str]) -> TreeNode:
    detail = [f"{SPEAKER.get(p.speaker, p.speaker)}（第{p.round}R）", _bridge_line(p)]
    if p.status in ("棄却", "審査通過・時期外", "一部のみ間に合う"):
        detail.append(p.reason)
    if len(parents) > 1:
        detail.append("複数のレバーにまたがる")
    return TreeNode(p.message_id, parents, "proposal", p.title, p.status, [d for d in detail if d])
