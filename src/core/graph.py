"""論争のステートマシン（LangGraph）。1発言＝1ノードで、各ノードの直前で必ず止まる。

  exploration   : radar → growth → rebuild → judge → （次のラウンドへ）
  triage_ready  : rebuild（宣告） → judge
  settlement    : judge が決着を宣言して終了

止めた状態は回次フォルダの checkpoints.sqlite に保存し、画面の再描画やアプリの再起動をまたいで続きから進める。
審査・監視指標・フェーズ判定は judge ノードの中でプログラムが行い、Judge（LLM）は中身の審理と論点整理だけを担う。
"""

from __future__ import annotations

import sqlite3

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from agents.base import DebateContext, Speaker, apply_agenda_ops, monitor_values, to_message
from agents.growth import Growth
from agents.moderator import Judge
from agents.rebuild import Rebuild
from agents.research import Radar
from agents.speakers import default_speaker
from core import guardrails as g
from core.metrics import project
from schema import DebateMessage, JudgeNote, OptionAssessment, PhaseDecision, ReviewResult, Ruling, SourceRef, stamp
from state import DebateState, checkpoint_types, initial_state

AGENTS = {"radar": Radar(), "growth": Growth(), "rebuild": Rebuild(), "judge": Judge()}
NODES = list(AGENTS)
ORDER = {"exploration": ("radar", "growth", "rebuild", "judge"), "triage_ready": ("rebuild", "judge")}
VERDICT_RANK = {"通過": 0, "差し戻し": 1, "退け": 2}


def next_in_round(phase: str, current: str) -> str:
    order = ORDER.get(phase, ("judge",))
    return order[order.index(current) + 1] if current in order[:-1] else "judge"


# ---------------------------------------------------------------------------
# 機械の審査（出典の実在、形式、フェーズの規律、繰り返し）
# ---------------------------------------------------------------------------
def formal_review(msg: DebateMessage, state: DebateState, registry: set[str], citation_index=None) -> ReviewResult:
    """形式審査（プログラム）。出典の実在、決着条件、因果ブリッジ、段階の規律、繰り返し、そして出典の照合。

    citation_index（core.citations.build_index）を渡すと、発言の中の数字が引用した頁に本当にあるかも確かめる。
    """
    reasons_pre: list[str] = []
    real = [s for s in msg.sources if (s.file or "") in registry]
    unknown = [s for s in msg.sources if (s.file or "") not in registry]
    if unknown:
        reasons_pre.append("資料一覧にない出典は審理に使いません：" + "、".join(s.label() for s in unknown))
    checked = msg.model_copy(update={"sources": real})
    r = g.review_debate_message(checked)
    reasons = reasons_pre + r.reasons
    if r.verdict != "通過":
        return ReviewResult(verdict=r.verdict, reasons=reasons, valid_sources=r.valid_sources)
    problems = g.phase_discipline(msg)
    if citation_index:
        from core import citations

        problems += citations.check(" ".join(x for x in (msg.headline, msg.text) if x), real, citation_index)
    passed_before = {g._norm_text(m.text) for m in state.messages
                     for x in state.rulings if x.message_id == m.id and x.verdict == "通過" and m.speaker == msg.speaker}
    if g._norm_text(msg.text) in passed_before:
        problems.append("以前に通過した主張の繰り返しです。新しい根拠か数字を示してください")
    if problems:
        return ReviewResult(verdict="差し戻し", reasons=reasons_pre + problems, valid_sources=r.valid_sources)
    return ReviewResult(verdict="通過", reasons=reasons, valid_sources=r.valid_sources)


def judge_note(rulings: list[Ruling], decision: PhaseDecision, summary: str, state: DebateState,
               monitor) -> JudgeNote:
    """Judge の裁定の中身。判定とフェーズはプログラムの結果をそのまま載せ、LLM の論点整理を添える。"""
    closing = ""
    if decision.rule == "triage_declared":
        closing = "次の手で、宣告された道を同じ物差しで比べます（選ぶのは人間です）。"
    elif decision.next == "settlement":
        tail = ("どの道を選ぶかは人間（経営者と金融機関）の判断に委ねます。"
                if state.triage_declared or decision.rule == "triage_declared"
                else "残った争点の決着には、各主張の決着条件に挙げたデータが必要です。")
        closing = f"論争を閉じます（止まった理由：{decision.stop_reason}）。{tail}"
    last: dict[str, Ruling] = {}
    for r in rulings:   # 同じ発言に審査と反論の見直しが重なったら、最後の判定で数える
        last[r.message_id] = r
    final = list(last.values())
    return JudgeNote(
        tally={v: sum(1 for r in final if r.verdict == v) for v in ("通過", "差し戻し", "退け")},
        sent_back=[f"{r.message_id}：{'減額採択' if r.reduced else r.verdict}（{r.reasons[0] if r.reasons else ''}）"
                   for r in final if r.verdict != "通過" or r.reduced or r.by == "challenge"],
        required_cf=monitor.base.required_cf, accumulated=monitor.accumulated_recovery_cf, gap=monitor.gap,
        runway=monitor.cash_runway_months, stalemate=monitor.stalemate_count, summary=summary.strip(),
        decision=decision, closing=closing,
    )


def judge_text(note: JudgeNote, state: DebateState) -> str:
    """裁定の文章（端末表示や記録用）。画面は judge_note を使って整理して見せる。"""
    t = note.tally
    lines = [f"第{state.round}ラウンドの審理：通過{t['通過']}件、差し戻し{t['差し戻し']}件、退け{t['退け']}件。"]
    lines += [f"・{x}" for x in note.sent_back]
    req = "—" if note.required_cf is None else f"{note.required_cf:,}"
    from core.metrics import runway_label

    rw = runway_label(note.runway, None if note.required_cf is None else note.accumulated - note.required_cf)
    lines.append(f"資金の監視：必要CF 年{req}千円に対し回収CF累計 {note.accumulated:,}千円、残余月数 {rw}、膠着{note.stalemate}回。")
    if note.summary:
        lines.append(note.summary)
    d = note.decision
    if d and d.changed:
        lines.append(f"【フェーズ判定】{d.current} → {d.next}。{d.reason}")
    if note.closing:
        lines.append(note.closing)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# グラフ
# ---------------------------------------------------------------------------
def build_graph(ctx: DebateContext, speaker: Speaker, policy: g.PhasePolicy = g.DEFAULT_POLICY) -> StateGraph:
    def speaking_node(agent_id: str):
        agent = AGENTS[agent_id]

        def node(state: DebateState) -> dict:
            turn = agent.speak(state, ctx, speaker)
            msg = to_message(turn, state, agent_id, ctx)
            if state.reply_to == agent_id:   # 人間に指名されて割り込んだ回答。答えたら元の順番に戻る
                nxt = state.resume_to or next_in_round(state.phase, agent_id)
            else:
                nxt = next_in_round(state.phase, agent_id)
            return {"messages": [msg], "agenda": apply_agenda_ops(state.agenda, turn.agenda_ops, state.round),
                    "next_speaker": nxt, "reply_to": None, "resume_to": None}

        return node

    def compare_step(state: DebateState) -> dict:
        """トリアージ宣告の後の決着段階：Judge が三つの道を同じ物差しで比べる。選ぶのは人間。"""
        from core.digest import triage

        tri = triage(state)
        options = tri.options if tri else []
        ct = AGENTS["judge"].compare(state, ctx, speaker, options)
        runway = state.monitor.cash_runway_months
        rows: list[OptionAssessment] = []
        for i, o in enumerate(options):
            a = ct.assessments[i] if i < len(ct.assessments) else None
            if a is None:
                rows.append(OptionAssessment(name=o.name, risks=["（Judge の評価が出ていません）"]))
                continue
            srcs = [SourceRef(file=ctx.resolve_source(x.file), page=str(x.page).lstrip("p.").strip() or None)
                    for x in a.sources]
            srcs = [x for x in srcs if x.file in ctx.registry]
            months = max(0, a.months_needed)
            rows.append(OptionAssessment(
                name=o.name, employment=a.employment, cash=a.cash, creditors=a.creditors, months_needed=months,
                risks=a.risks, deciding_fact=a.deciding_fact, sources=srcs,
                in_time=None if runway is None else months < runway))
        late = [r.name for r in rows if r.in_time is False]
        note = ("" if not late else "残余月数のうちに道筋がつかない見込みの道：" + "、".join(late) + "。") + \
            "どの道を選ぶかは人間（経営者と金融機関）の判断に委ねます。"
        msg = DebateMessage(at=stamp(), id=f"R{state.round}-judge-{len(state.messages) + 1}", round=state.round,
                            phase="settlement", speaker="judge", action="比較",
                            text=((ct.summary.strip() + "\n") if ct.summary else "") + note,
                            sources=[SourceRef(file="プログラムの判定", page="-")], comparison=rows)
        return {"messages": [msg], "next_speaker": None, "stop_reason": "トリアージ宣告"}

    def judge_node(state: DebateState) -> dict:
        if state.phase == "settlement" and state.triage_declared and state.stop_reason is None:
            return compare_step(state)
        ruled = {r.message_id for r in state.rulings}
        targets = [m for m in state.messages if m.round == state.round and m.id not in ruled
                   and m.speaker not in ("judge", "human")]
        formal = {m.id: formal_review(m, state, ctx.registry, ctx.citation_index()) for m in targets}
        passed = [m for m in targets if formal[m.id].verdict == "通過"]
        jt = AGENTS["judge"].review(state, ctx, speaker, passed)
        content = {c.message_id: c for c in jt.reviews}
        new: list[Ruling] = []
        for m in targets:
            f = formal[m.id]
            verdict, reasons = f.verdict, list(f.reasons)
            c = content.get(m.id)
            if c and VERDICT_RANK[c.verdict] > VERDICT_RANK[verdict]:   # 中身の審理は厳しくする方向にだけ効く
                verdict, reasons = c.verdict, [f"中身の審理：{c.reason}"] + reasons
            new.append(Ruling(message_id=m.id, round=state.round, verdict=verdict, reasons=reasons))
        from core.challenge import challenge_rulings

        chal = challenge_rulings(state.messages, state.rulings + new, state.round)   # 反論による差し戻し・減額採択
        new = new + chal
        rulings = state.rulings + new
        stalemate = g.update_stalemate(state.monitor.stalemate_count, state.round, state.messages, rulings)
        after = state.model_copy(update={"rulings": rulings})
        monitor = project(state.monitor.base, after.passed_bridges(), stalemate, state.round - state.reopen_base)
        monitor = monitor.model_copy(update={"levers_tried": g.levers_tried(state.messages, rulings)})
        declared = state.triage_declared or any(
            r.verdict == "通過" and m.speaker == "rebuild" and m.action == "宣告"
            for r in new for m in targets if m.id == r.message_id)
        decision = g.decide_phase(state.phase, monitor, declared, policy)
        agenda = apply_agenda_ops(state.agenda, jt.agenda_ops, state.round)
        after_decl = state.model_copy(update={"triage_declared": declared})
        note = judge_note(new, decision, jt.summary, after_decl, monitor)
        jmsg = DebateMessage(at=stamp(), id=f"R{state.round}-judge-{len(state.messages) + 1}", round=state.round,
                             phase=state.phase, speaker="judge", action="裁定", text=judge_text(note, state),
                             sources=[SourceRef(file="プログラムの判定", page="-")],
                             settle_condition=None, judge_note=note)
        compare_next = decision.rule == "triage_declared"   # 宣告の後は、道の比較を1手はさんでから閉じる
        done = decision.next == "settlement" and not compare_next
        return {
            "messages": [jmsg], "rulings": new, "phase_history": [decision], "monitor": monitor,
            "phase": decision.next, "triage_declared": declared, "agenda": agenda,
            "round": state.round if done else state.round + 1,
            "next_speaker": None if done else ("judge" if compare_next else ORDER[decision.next][0]),
            "stop_reason": decision.stop_reason if done else None,
        }

    def route(state: DebateState) -> str:
        return END if state.next_speaker is None else state.next_speaker

    gr = StateGraph(DebateState)
    for a in ("radar", "growth", "rebuild"):
        gr.add_node(a, speaking_node(a))
    gr.add_node("judge", judge_node)
    targets = {n: n for n in NODES} | {END: END}
    gr.add_conditional_edges(START, route, targets)
    for n in NODES:
        gr.add_conditional_edges(n, route, targets)
    return gr


# ---------------------------------------------------------------------------
# 回次ごとの論争セッション（画面から使う窓口）
# ---------------------------------------------------------------------------
class DebateSession:
    """ある分析回次の論争。1手ずつ進め、どこで止めても checkpoints.sqlite から再開できる。"""

    DB_NAME = "checkpoints.sqlite"

    def __init__(self, run, speaker: Speaker | None = None, policy: g.PhasePolicy = g.DEFAULT_POLICY,
                 readonly: bool = False):
        self.run = run
        self.ctx = DebateContext.from_run(run)
        self.speaker = speaker or default_speaker()
        db = run.path / self.DB_NAME
        if readonly:   # 比較画面などで読むだけ。凍結した回次のファイルに手を触れない
            self._conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, check_same_thread=False)
        else:
            self._conn = sqlite3.connect(db, check_same_thread=False)
        saver = SqliteSaver(self._conn, serde=JsonPlusSerializer(allowed_msgpack_modules=checkpoint_types()))
        self.app = build_graph(self.ctx, self.speaker, policy).compile(checkpointer=saver, interrupt_before=NODES)
        self.config = {"configurable": {"thread_id": f"{run.company}/{run.run_id}"}}

    # --- 状態 ---------------------------------------------------------------
    @property
    def started(self) -> bool:
        return bool(self.app.get_state(self.config).values)

    def state(self) -> DebateState | None:
        v = self.app.get_state(self.config).values
        return DebateState.model_validate(v) if v else None

    @property
    def next_node(self) -> str | None:
        nxt = self.app.get_state(self.config).next
        return nxt[0] if nxt else None

    @property
    def finished(self) -> bool:
        return self.started and self.next_node is None

    # --- 操作 ---------------------------------------------------------------
    def _guard(self) -> None:
        if self.run.frozen:
            from core.runs import FrozenRunError

            raise FrozenRunError(f"{self.run.run_id} は凍結済みです。論争は最新の回次で進めてください")

    def start(self) -> DebateState:
        """論争を始め、最初の発言者の直前で止める（まだ誰も話していない）。"""
        self._guard()
        if not self.started:
            self.app.invoke(initial_state(self.run.company, self.run.run_id, self.ctx.base, self.ctx.mission),
                            self.config)
        return self.state()

    NOMINABLE = ("radar", "growth", "rebuild")

    def can_nominate(self) -> bool:
        """発言者を指名できるか。探索段階だけ（トリアージ段階の宣告は Rebuild、決着段階は Judge に固定）。"""
        st = self.state() if self.started else None
        return not self.finished and (st is None or st.phase == "exploration")

    def step(self, speaker: str | None = None) -> list[DebateMessage]:
        """［1手進める］次のノードを一つだけ実行して止まる。新しく加わった発言を返す。

        speaker（radar／growth／rebuild）を指名すると、その担当者が順番を割り込んで話し、話し終えたら元の順番に
        戻る（Judge の番だったなら Judge が、指名発言も含めてそのラウンドを審理する）。
        """
        self._guard()
        if not self.started:
            self.start()
        if self.finished:
            return []
        if speaker is not None:
            if speaker not in self.NOMINABLE:
                raise ValueError(f"指名できるのは {self.NOMINABLE} です")
            if not self.can_nominate():
                raise ValueError("発言者を指名できるのは探索段階だけです")
            st = self.state()
            if st.next_speaker != speaker:
                self.app.update_state(self.config, {"next_speaker": speaker, "reply_to": speaker,
                                                    "resume_to": st.next_speaker})
        before = len(self.state().messages)
        self.app.invoke(None, self.config)
        return self.state().messages[before:]

    def run_round(self, max_steps: int = 8) -> list[DebateMessage]:
        """［次のラウンドへ］Judge の審理（とフェーズ判定）が終わるまで進めて止まる。"""
        out: list[DebateMessage] = []
        for _ in range(max_steps):
            if self.finished:
                break
            node = self.next_node or "radar"
            out += self.step()
            if node == "judge":
                break
        return out

    def needs_comparison(self) -> bool:
        """トリアージが宣告されて閉じたのに、道の比較がない（比較の手順を入れる前に終わった論争）。"""
        st = self.state()
        return bool(st and self.finished and st.triage_declared
                    and not any(m.action == "比較" for m in st.messages))

    def add_comparison(self) -> list[DebateMessage]:
        """閉じた論争に、道の比較を1手だけ追加する。"""
        self._guard()
        if not self.needs_comparison():
            return []
        self.app.update_state(self.config, {"next_speaker": "judge", "stop_reason": None}, as_node="judge")
        return self.step()

    def adopt(self, option: str, note: str = "") -> None:
        """人間（経営者・金融機関との協議の結果）が選んだ道を、採択として記録する。論争の中身は変えない。"""
        from schema import DebateMessage as _M

        self._guard()
        st = self.state()
        if st is None or not self.finished:
            raise ValueError("採択を記録できるのは、論争が閉じた後です")
        text = f"採択：{option}" + (f"（{note.strip()}）" if note and note.strip() else "")
        msg = _M(at=stamp(), id=f"R{st.round}-human-{len(st.messages) + 1}", round=st.round, phase=st.phase,
                 speaker="human", action="介入", text=text)
        self.app.update_state(self.config, {"adopted_option": option, "adopted_note": note.strip(), "messages": [msg]},
                              as_node="judge")

    def reopen(self, reason: str) -> DebateState:
        """閉じた論争を、人間の求めで探索段階に戻す（充足・膠着・上限・宣告のどれで閉じた後でも）。

        発言・判定・フェーズの履歴は消さずに積み上げる（再開そのものをフェーズの履歴と Judge の発言に残す）。
        ラウンドの上限と膠着は、再開からの数で数え直す。宣告は取り消さず履歴に残るが、改めて宣告されるまで効かない。
        """
        self._guard()
        st = self.state()
        if st is None or not self.finished:
            raise ValueError("再開できるのは、閉じた論争だけです")
        nxt_round = st.round + 1
        decision = PhaseDecision(round=st.round, current=st.phase, next="exploration", rule="reopened",
                                 reason=f"人間の求めで論争を再開します（{reason}）。第{nxt_round}ラウンドから探索に戻ります",
                                 stop_reason=None)
        note = DebateMessage(at=stamp(), id=f"R{st.round}-judge-{len(st.messages) + 1}", round=st.round, phase=st.phase,
                             speaker="judge", action="裁定",
                             text=f"論争を再開します（前回の止まった理由：{st.stop_reason}）。{reason}。"
                                  f"第{nxt_round}ラウンドから探索に戻り、新しい条件のもとで改めて審理します。",
                             sources=[SourceRef(file="プログラムの判定", page="-")])
        monitor = st.monitor.model_copy(update={"stalemate_count": 0, "rounds_completed": 0})
        self.app.update_state(self.config, {
            "messages": [note], "phase_history": [decision], "phase": "exploration", "triage_declared": False,
            "stop_reason": None, "round": nxt_round, "next_speaker": "radar", "reopen_base": st.round,
            "reopened": st.reopened + 1, "monitor": monitor}, as_node="judge")
        return self.state()

    def set_mission(self, mission: str) -> None:
        """診断ミッションを変える。論争が始まった後の変更は、人間の介入として記録に残す。"""
        from schema import DebateMessage as _M

        self._guard()
        mission = (mission or "").strip()
        if not mission:
            raise ValueError("診断ミッションが空です")
        if not self.started:
            self.app.invoke(initial_state(self.run.company, self.run.run_id, self.ctx.base, mission), self.config)
            return
        st = self.state()
        if mission == st.mission:
            return
        if self.finished:   # 閉じた後にミッションを変えたら、新しい目的で論争を再開する
            self.reopen("診断ミッションの変更")
            st = self.state()
        note = _M(at=stamp(), id=f"R{st.round}-human-{len(st.messages) + 1}", round=st.round, phase=st.phase, speaker="human",
                  action="介入", text=f"診断ミッションを「{st.mission}」から「{mission}」に変更しました")
        self.app.update_state(self.config, {"mission": mission, "messages": [note]})

    def close(self) -> None:
        self._conn.close()
