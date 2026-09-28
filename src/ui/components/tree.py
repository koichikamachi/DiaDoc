"""タブ3：意思決定ツリー（Graphviz）。回次の decision_tree.json を描く。"""

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


def render(tree: dict | None) -> None:
    if not tree:
        st.info("この回次にはまだツリーがありません。")
        return
    st.markdown("##### 検討されたシナリオと採否")
    st.caption("凡例：" + "　".join(f"{v[3]} {k}" for k, v in STYLE.items()))
    st.graphviz_chart(build(tree), width="stretch")
    st.markdown("##### 棄却・除外の理由")
    for n in tree["nodes"]:
        if n["status"] in ("棄却", "制約により除外"):
            with st.container(border=True):
                st.markdown(f"**{n['id']}　{n['label']}**　:gray-badge[{n['status']}]")
                st.caption(f"{n['reason']}（{n['source']}）")
