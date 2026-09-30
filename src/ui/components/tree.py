"""タブ3：意思決定ツリー（Graphviz）。

render_live は論争の状態から毎回組み立てたツリー（core.decision_tree）を描く。論争が一手進むたびに枝が増える。
render は旧・静的ツリー（回次の decision_tree.json）。参考として折りたたみの中に残す。
"""

from __future__ import annotations

import graphviz
import streamlit as st

# 状態ごとの配色（塗り、枠、文字）。明暗どちらの背景でも読めるよう、淡い塗りに濃い文字を置く
STYLE = {
    "棄却": ("#fbe9e9", "#c43c3b", "#6b1b1b", "×"),
    "条件付き採用": ("#e6f1fb", "#2a78d6", "#0c3e75", "◎"),
    "採用候補": ("#e3f5ec", "#1a8a5f", "#0b4a32", "○"),
    "保留": ("#f1efe8", "#888780", "#3d3d3a", "…"),
    "制約により除外": ("#f3eefb", "#6a5acd", "#3a2f7a", "⊘"),
}


def _wrap(text: str, width: int = 13) -> str:
    """日本語を指定幅で折り返す。数字や小数点の途中では改行しない。"""
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if len(cur) >= width:
            cut = len(cur)
            while cut > 1 and (cur[cut - 1].isdigit() or cur[cut - 1] in ".,%") and cut < len(cur) + 1:
                if cut < len(cur) and not (cur[cut].isdigit() or cur[cut] in ".,%"):
                    break
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
    if cur:
        lines.append(cur)
    return "\\n".join(lines)


def build(tree: dict) -> graphviz.Digraph:
    g = graphviz.Digraph("decision")
    g.attr(rankdir="TB", bgcolor="transparent", nodesep="0.35", ranksep="0.55")
    g.attr("node", shape="box", style="rounded,filled", fontname="sans-serif", fontsize="11", margin="0.30,0.14", width="2.4")
    g.attr("edge", color="#888780", arrowsize="0.6")
    g.node("root", tree["root"], fillcolor="#3d3d3a", color="#3d3d3a", fontcolor="#ffffff", fontsize="12")
    for n in tree["nodes"]:
        fill, border, ink, mark = STYLE.get(n["status"], STYLE["保留"])
        label = f"{n['id']}　{_wrap(n['label'], 12)}\\n{mark} {n['status']}\\n\\n{_wrap(n['reason'])}"
        g.node(n["id"], label, fillcolor=fill, color=border, fontcolor=ink, penwidth="1.4")
        g.edge(n.get("parent") or "root", n["id"])
    return g


def _chart(dot, name: str) -> None:
    """図は画面の高さに収めて縮小表示する（ブラウザを拡大しても図だけが肥大化しない）。実寸表示に切り替えるとスクロールで見る。"""
    full = st.toggle("図を実寸で見る（スクロール）", key=f"tree_full_{name}", value=False)
    with st.container(key=f"dd-tree-{'full' if full else 'fit'}-{name}"):
        st.graphviz_chart(dot, width="content" if full else "stretch")


def render(tree: dict | None) -> None:
    if not tree:
        st.info("この回次にはまだツリーがありません。")
        return
    st.markdown("##### 検討されたシナリオと採否")
    st.caption("凡例：" + "　".join(f"{v[3]} {k}" for k, v in STYLE.items()))
    _chart(build(tree), "static")
    st.markdown("##### 棄却・除外の理由")
    for n in tree["nodes"]:
        if n["status"] in ("棄却", "制約により除外"):
            with st.container(border=True):
                st.markdown(f"**{n['id']}　{n['label']}**　:gray-badge[{n['status']}]")
                st.caption(f"{n['reason']}（{n['source']}）")


# 論争から育つツリーの配色（塗り、枠、文字、記号、枠線の種類）。淡い塗りに濃い文字で、明暗どちらの背景でも読める
LIVE_STYLE = {
    # 提案（審査と資金の時間軸）
    "審査通過・時期内": ("#e3f5ec", "#1a8a5f", "#0b4a32", "◎", "solid"),
    "一部のみ間に合う": ("#e6f1fb", "#2a78d6", "#0c3e75", "◐", "solid"),
    "審査通過・時期外": ("#f3eefb", "#6a5acd", "#3a2f7a", "◷", "solid"),
    "減額採択": ("#fdf3e1", "#c98a1a", "#6b4a0b", "▽", "solid"),
    "棄却": ("#fbe9e9", "#c43c3b", "#6b1b1b", "×", "solid"),
    "審理中": ("#f1efe8", "#888780", "#3d3d3a", "…", "dashed"),
    # レバー
    "未着手": ("#f7f6f2", "#b4b2a9", "#6b6a64", "○", "dashed"),
    "通過あり": ("#e3f5ec", "#1a8a5f", "#0b4a32", "●", "solid"),
    "棄却のみ": ("#fbe9e9", "#c43c3b", "#6b1b1b", "×", "solid"),
    # トリアージと道
    "宣告": ("#fdeee6", "#eb6834", "#7a2e0e", "✚", "solid"),
    "時期内": ("#e3f5ec", "#1a8a5f", "#0b4a32", "✓", "solid"),
    "時期外": ("#f3eefb", "#6a5acd", "#3a2f7a", "✕", "solid"),
    "比較待ち": ("#f1efe8", "#888780", "#3d3d3a", "…", "dashed"),
    "比較済み": ("#f1efe8", "#888780", "#3d3d3a", "・", "solid"),
    "採択": ("#3d3d3a", "#3d3d3a", "#ffffff", "★", "bold"),
    "不採択": ("#f7f6f2", "#b4b2a9", "#6b6a64", "－", "dashed"),
    # 前提（人間の介入）
    "前提": ("#fff8e1", "#b58900", "#5c4400", "●", "solid"),
}
STATUS_WORD = {"通過あり": "審査を通った提案あり", "未着手": "まだ提案がない", "棄却のみ": "提案はすべて棄却",
               "宣告": "Rebuild の宣告（審査通過）", "時期内": "時期内", "時期外": "時期外"}


def build_live(nodes) -> graphviz.Digraph:
    g = graphviz.Digraph("live")
    g.attr(rankdir="LR", bgcolor="transparent", nodesep="0.25", ranksep="0.5")
    g.attr("node", shape="box", style="rounded,filled", fontname="sans-serif", fontsize="10.5", margin="0.34,0.12")
    g.attr("edge", color="#888780", arrowsize="0.6")
    for n in nodes:
        if n.kind == "root":
            label = f"診断ミッション\\n{_wrap(n.label, 14)}\\n\\n{n.detail[0]}"
            g.node(n.id, label, fillcolor="#3d3d3a", color="#3d3d3a", fontcolor="#ffffff", fontsize="11.5")
            continue
        fill, border, ink, mark, line = LIVE_STYLE.get(n.status, LIVE_STYLE["審理中"])
        head = f"{n.id}　" if n.kind == "proposal" else ""
        width = 14 if n.kind in ("proposal", "option", "triage") else 11
        body = "\\n".join(_wrap(d, 17) for d in n.detail)
        label = f"{head}{_wrap(n.label, width)}\\n{mark} {STATUS_WORD.get(n.status, n.status)}" + (f"\\n\\n{body}" if body else "")
        style = "rounded,filled" + (",dashed" if line == "dashed" else ",bold" if line == "bold" else "")
        shape = "note" if n.kind == "premise" else "box"
        g.node(n.id, label, fillcolor=fill, color=border, fontcolor=ink, style=style, shape=shape, penwidth="1.4")
        for parent in n.parents:
            g.edge(parent, n.id, style="dashed" if n.kind == "premise" else "solid")
    return g


def render_live(state, mission: str | None = None) -> None:
    from core import decision_tree

    nodes = decision_tree.build(state, mission)
    st.markdown("##### 論争から育つ意思決定ツリー")
    st.caption("論争が一手進むたびに、プログラムが状態から描き直します。根＝診断ミッション、枝＝改善の4レバー、"
               "葉＝提案（審査と資金の時間軸で見た採否）。複数のレバーにまたがる提案は、それぞれのレバーから枝が伸びます。"
               "トリアージの宣告が審査を通ると「Level 0 の道」の枝が生え、Judge の比較と人間の採択が重なります。")
    _chart(build_live(nodes), "live")
    marks = ["◎ 審査通過・時期内", "◐ 一部のみ間に合う", "◷ 審査通過・時期外", "▽ 減額採択（反論を受けて資金効果を減らした）", "× 棄却", "… 審理中", "○ 未着手のレバー",
             "✓✕ 道筋がつくか（残余月数と比べてプログラムが判定）", "★ 人間が記録した採択"]
    st.caption("凡例：" + "　".join(marks))
