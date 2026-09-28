"""（参考）旧・静的分析ログの表示。LangGraph 接続前の台本による論争の記録を、当時のまま読むためだけに残す。"""

from __future__ import annotations

import streamlit as st

import mock_data as md
from core.mock_engine import review_message


def _sources_label(sources: list[dict]) -> str:
    out = []
    for s in sources:
        out.append(f"{s.get('file') or '（書類不明）'}" + (f" p.{s['page']}" if s.get("page") else ""))
    return "、".join(out)


def _render_message(m: dict) -> None:
    a = md.AGENTS[m["who"]]
    with st.chat_message(a["name"], avatar=a["avatar"]):
        header = f":{a['color']}[**{a['name']}**]　:gray[{a['role']}・{m['phase']}]"
        if m.get("ruling") in md.RULING_BADGE:
            color, label = md.RULING_BADGE[m["ruling"]]
            header += f"　:{color}-badge[{label}]"
        review = review_message(m)
        if review is not None:
            color, label = md.REVIEW_BADGE[review.verdict]
            header += f"　:{color}-badge[{label}]"
        st.markdown(header)
        st.markdown(m["text"])
        meta = []
        if m.get("sources"):
            meta.append("出典：" + _sources_label(m["sources"]))
        claim = m.get("claim") or {}
        if claim.get("settle_condition"):
            meta.append("決着条件：" + claim["settle_condition"])
        if review is not None and review.verdict != "通過":
            meta.append("形式審査：" + review.reasons[0])
        if meta:
            st.caption("　／　".join(meta))


def render(messages: list[dict], constraints: dict) -> None:
    n_turn = sum(1 for m in messages if m["who"] == "human")
    st.caption(f"発言 {len(messages)} 件　／　介入・投入 {n_turn} 回")
    for m in messages:
        _render_message(m)
    if constraints.get("constraints"):
        st.markdown("**当時登録された制約**")
        for c in constraints["constraints"]:
            st.markdown(f"- {c}")
