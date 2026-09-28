"""人間の介入（ライム）。止まっている論争に、コメントや追加資料の要点を書き込む。

介入は発言として積むが、審判の審理や膠着の計算には入れない（人間の言葉は論争の当事者の主張ではなく条件である）。
各エージェントは次の手から、文脈の中でこの介入を読む。
"""

from __future__ import annotations

from core.graph import DebateSession
from schema import DebateMessage, SourceRef, stamp


class EmptyInterventionError(ValueError):
    pass


ADDRESSABLE = ("radar", "growth", "rebuild")


def intervene(session: DebateSession, text: str, sources: list[SourceRef] | None = None,
              attach_name: str | None = None, attach_text: str | None = None,
              addressee: str | None = None) -> DebateMessage:
    """介入を書き込む。

    attach_text を渡すと、その資料（ヒアリングメモなど）を引用できる資料に加える。
    addressee（radar／growth／rebuild）を渡すと、その担当者が順番を割り込んで次に答え、答えた後は元の順番に戻る。
    指名しなければ、次の発言者がこの介入を読んで答える。
    """
    session._guard()
    text = (text or "").strip()
    if not text and not attach_text:
        raise EmptyInterventionError("介入の内容が空です")
    if not session.started:
        session.start()
    st = session.state()
    if attach_name and attach_text:
        saved = session.run.save_input(f"{attach_name}.md", attach_text.encode("utf-8"))
        session.ctx.materials[saved.stem] = attach_text
        text = text or f"資料「{saved.stem}」を追加しました"
    if addressee is not None and addressee not in ADDRESSABLE:
        raise ValueError(f"宛先にできるのは {ADDRESSABLE} です")
    msg = DebateMessage(at=stamp(), id=f"R{st.round}-human-{len(st.messages) + 1}", round=st.round, phase=st.phase,
                        speaker="human", action="介入", text=text, sources=sources or [], addressee=addressee)
    update: dict = {"messages": [msg]}
    if addressee and not session.finished and st.next_speaker != addressee:
        update |= {"next_speaker": addressee, "reply_to": addressee, "resume_to": st.next_speaker}
    elif addressee and not session.finished:
        update |= {"reply_to": addressee}
    session.app.update_state(session.config, update)
    return msg
