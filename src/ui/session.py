"""回次ごとの論争セッション（LangGraph）を、画面の再描画をまたいで一つだけ保つ。

状態そのものは回次フォルダの checkpoints.sqlite にあるので、ここで持つのは接続とグラフだけである。
"""

from __future__ import annotations

import streamlit as st

from core.graph import DebateSession
from core.runs import Run


def get_session(run: Run) -> DebateSession:
    key = f"dbd_session::{run.company}/{run.run_id}"
    ss = st.session_state
    if key not in ss:
        ss[key] = DebateSession(run)
    return ss[key]


def forget(run: Run) -> None:
    key = f"dbd_session::{run.company}/{run.run_id}"
    s = st.session_state.pop(key, None)
    if s is not None:
        s.close()


def reset(run: Run) -> None:
    """この回次の論争を最初からやり直す（途中状態と発言生成の記録を消す）。投入した資料は消さない。"""
    from core.runs import FrozenRunError

    if run.frozen:
        raise FrozenRunError("凍結済みの回次はやり直せません")
    forget(run)
    for p in list(run.path.glob(DebateSession.DB_NAME + "*")) + [run.path / "debate_trace.jsonl"]:
        if p.exists():
            p.unlink()
