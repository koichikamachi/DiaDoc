"""中央ペイン：操作デッキと、発言タイムライン、人間の介入欄。"""

from __future__ import annotations

import html

import streamlit as st

from agents_profile import PHASE, PROFILES
from theme import agent_color
from core import export
from core.graph import DebateSession
from core.interrupt import EmptyInterventionError, intervene
from schema import DebateMessage
from state import DebateState

TIMELINE_HEIGHT = 540


def csv_name(session) -> str:
    return f"DiaDoc_{session.run.company}_{session.run.run_id}_議論ログ.csv"
LONG_TEXT = 240   # これより長い発言は冒頭だけ見せて折りたたむ


def _verdicts(state: DebateState) -> dict[str, tuple[str, list[str]]]:
    out: dict[str, tuple[str, list[str]]] = {}
    for r in state.rulings:
        out[r.message_id] = ("減額採択" if r.reduced else r.verdict, r.reasons)
    return out


def _counted(state: DebateState) -> dict[tuple[str, str], bool]:
    return {(c.message_id, c.bridge.account): c.in_time for c in state.monitor.counted}


def _bridge_html(m: DebateMessage, counted: dict) -> str:
    from tools.standard_accounts import LABELS

    rows = []
    for b in m.bridges:
        in_time = counted.get((m.id, b.account))
        tag = "" if in_time is None else ("✓ 間に合う" if in_time else "✕ 資金が尽きた後")
        cls = ' class="dd-late"' if in_time is False else ""
        rows.append(
            f'<div class="dd-bridge"><span>⇢ <b>{html.escape(LABELS.get(b.account, b.account))}</b> {b.direction}</span>'
            f'<span>変動 <b>{b.amount:,}</b></span><span{cls}>資金 <b>{b.cf_effect:+,}</b>'
            f'{"／年" if b.recurring else "（一回）"}</span><span>{b.lead_months}か月後</span>'
            f'<span class="dd-when">{html.escape(tag)}</span></div>')
    return "".join(rows)


VERDICT_CLASS = {"通過": ("ok", "✓"), "減額採択": ("back", "▽"), "差し戻し": ("back", "↩"), "退け": ("rej", "✕")}


def _header_html(m: DebateMessage, verdict: str | None) -> str:
    """発言者を大きく示す見出し。色の丸（識別の補助）＋名前（大）＋肩書（小）＋判定。"""
    p = PROFILES[m.speaker]
    color = agent_color(m.speaker)
    v = ""
    if verdict:
        cls, mark = VERDICT_CLASS[verdict]
        v = f'<span class="dd-verdict dd-{cls}">{mark} {verdict}</span>'
    glyph_ink = "#ffffff" if m.speaker in ("radar", "rebuild", "growth") else "var(--dd-card)"
    return (f'<div class="dd-speaker"><span class="dd-av" style="background:{color};color:{glyph_ink}">{p["glyph"]}</span>'
            f'<span class="dd-name">{html.escape(p["name"])}</span>'
            f'<span class="dd-role">{html.escape(p["title"])}（{html.escape(p["duty"])}）</span>'
            f'<span class="dd-meta">{html.escape(m.action)}｜第{m.round}ラウンド</span>{v}</div>')


def _split_long(text: str, limit: int = LONG_TEXT) -> tuple[str, str | None]:
    """長い発言は最初の数文だけを見せ、残りを折りたたむ。文の途中では切らない。"""
    if len(text) <= limit:
        return text, None
    cut = 0
    for i, ch in enumerate(text):
        if ch in "。\n" and i + 1 >= limit * 0.45:
            cut = i + 1
            break
    if cut == 0 or cut >= len(text) - 20:
        cut = limit
    return text[:cut], text[cut:]


def _options_html(m: DebateMessage) -> str:
    rows = []
    for o in m.options:
        rows.append(
            f'<div class="dd-option"><div class="dd-option-name">{html.escape(o.name)}</div>'
            f'<div><span class="dd-k">残す</span>{html.escape("・".join(o.keep) or "—")}</div>'
            f'<div><span class="dd-k">捨てる</span>{html.escape("・".join(o.discard) or "—")}</div>'
            f'<div><span class="dd-k">前提</span>{html.escape("／".join(o.preconditions) or "—")}</div></div>')
    return '<div class="dd-options">' + "".join(rows) + "</div>"


def _judge_body(m: DebateMessage) -> None:
    n = m.judge_note
    t = n.tally
    chips = "".join(f'<span class="dd-verdict dd-{VERDICT_CLASS[k][0]}">{VERDICT_CLASS[k][1]} {k} {t.get(k, 0)}件</span>'
                    for k in ("通過", "差し戻し", "退け"))
    pending = bool(n.pending)
    req = "判定保留" if pending else ("—" if n.required_cf is None else f"{n.required_cf:,}")
    gap = "判定保留" if pending else ("—" if n.gap is None else f"{n.gap:,}")
    from core.metrics import runway_label

    net = None if n.required_cf is None else n.accumulated - n.required_cf
    rw = runway_label(n.runway, net, short=True, pending=pending)
    st.html(f'<div class="dd-tally">{chips}</div>'
            f'<div class="dd-mini"><span>必要CF<b>{req}</b></span>'
            f'<span title="損益の改善による毎年の資金（ラン）">継続改善CF（年）<b>{n.accumulated:,}</b></span>'
            f'<span title="資産売却などの一回限りの資金（ショット）">一括調達（一時的資金）<b>{n.one_time:,}</b></span>'
            f'<span>不足<b>{gap}</b></span><span>残余月数<b>{rw}</b></span><span>膠着<b>{n.stalemate}回</b></span></div>')
    if n.confirmed:
        st.caption(":material/fact_check: " + n.confirmed)
    if pending:
        st.html(f'<div class="dd-phase"><b>資金不足の有無：判定保留（返済予定表の開示待ち）</b><br>'
                f'{html.escape(n.pending)}<br>{html.escape(n.reference)}</div>')
    for x in n.sent_back:
        st.markdown(f":orange[:material/undo:] {x}")
    if n.summary:
        st.markdown(n.summary)
    d = n.decision
    if d and d.changed:
        cur, nxt = PHASE[d.current]["label"], PHASE[d.next]["label"]
        st.html(f'<div class="dd-phase dd-phase-{d.next}"><b>フェーズ判定（プログラム）：{cur} → {nxt}</b><br>'
                f'{html.escape(d.reason)}</div>')
    elif d and d.rule == "levers_remaining":   # 資金は足りないが、未着手のレバーがあるので探索を続ける（あがき）
        st.html(f'<div class="dd-phase"><b>フェーズ判定（プログラム）：探索を続ける</b><br>{html.escape(d.reason)}</div>')
    if n.closing:
        st.markdown(f":material/flag: **{n.closing}**")


def comparison_html(m: DebateMessage, runway: float | None) -> str:
    """トリアージの道の比較表。行＝物差し、列＝道。どれかを推すことはしない。"""
    rows_def = [
        ("雇用", lambda a: html.escape(a.employment or "—")),
        ("資金繰り", lambda a: html.escape(a.cash or "—")),
        ("債権者に求めること", lambda a: html.escape(a.creditors or "—")),
        ("道筋がつくまで", lambda a: "—" if a.months_needed is None else (
            f'<b>{a.months_needed}か月</b>　' + ("" if a.in_time is None else (
                '<span class="dd-verdict dd-ok">✓ 残余月数内</span>' if a.in_time
                else '<span class="dd-verdict dd-rej">✕ 残余月数を超える</span>')))),
        ("主なリスク", lambda a: "<br>".join("・" + html.escape(x) for x in a.risks) or "—"),
        ("決め手になる事実", lambda a: html.escape(a.deciding_fact or "—")),
        ("根拠", lambda a: "、".join(html.escape(x.label()) for x in a.sources) or "—"),
    ]
    head = "".join(f"<th>{html.escape(a.name)}</th>" for a in m.comparison)
    body = "".join(f"<tr><th>{k}</th>" + "".join(f"<td>{f(a)}</td>" for a in m.comparison) + "</tr>"
                   for k, f in rows_def)
    rw = "資金流出なし" if runway is None else f"残余月数 約{runway:.1f}か月"
    return (f'<div class="dd-cmp-wrap"><table class="dd-cmp"><thead><tr><th>物差し（{rw}）</th>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def _card(m: DebateMessage, verdicts: dict, counted: dict, runway: float | None = None) -> None:
    v = verdicts.get(m.id)
    with st.container(border=True, key=f"card-{m.speaker}-{m.id}"):
        st.html(_header_html(m, v[0] if v else None))
        if m.speaker == "judge" and m.judge_note is not None:
            _judge_body(m)
            return
        if m.action == "比較" and m.comparison:
            st.markdown("**Level 0 の道の比較**　:gray[同じ物差しで並べたもの。どれを選ぶかは人間が決めます]")
            st.html(comparison_html(m, runway))
            st.markdown(m.text.replace("\n", "  \n"))
            return
        if m.speaker == "human" and m.addressee:
            st.markdown(f":gray[:material/subdirectory_arrow_right: {PROFILES[m.addressee]['name']} 宛て]")
        if m.target_message:
            from tools.standard_accounts import LABELS

            what = f"「{LABELS.get(m.challenged_account, m.challenged_account)}」" if m.challenged_account else "提案全体"
            if m.action == "攻撃":
                cf = ("見込めない（0）" if not m.feasible_cf else f"{m.feasible_cf:,}千円（年）") if m.feasible_cf is not None \
                    else "示されていない"
                st.markdown(f":gray[:material/reply: {m.target_message} への反論　疑義：{what}　現実的な資金効果：{cf}]")
            else:
                st.markdown(f":gray[:material/shield: {m.target_message} への防御]")
        head, rest = _split_long(m.text)
        st.markdown(head.replace("\n", "  \n"))
        if m.options:
            st.html(_options_html(m))
        if m.bridges:
            st.html(_bridge_html(m, counted))
        if rest:
            with st.expander("続きを読む（全文）", icon=":material/unfold_more:"):
                st.markdown(rest.replace("\n", "  \n"))
        details = []
        if m.sources and m.speaker != "judge":
            details.append("**根拠**　" + "、".join(s.label() for s in m.sources))
        if m.settle_condition:
            details.append("**決着条件**　" + m.settle_condition)
        if v and v[1]:
            details.append("**審査の理由**　" + "／".join(v[1]))
        if details:
            with st.expander("根拠と審査", icon=":material/fact_check:"):
                st.markdown("\n\n".join(details))


def _request(action: str, nonce: int, can_pick: bool) -> None:
    """ボタンの受付。押された時点の発言数（nonce）と一緒に記録し、実行は本体で一度だけ行う。

    処理中に連打されても、発言数が変わった後の要求は古いものとして捨てる（二重実行の防止）。
    指名は1手ごとに「自動」に戻す。
    """
    ss = st.session_state
    pick = ss.get("next_pick", "auto")
    ss.dd_pending = {"action": action, "nonce": nonce, "speaker": pick if can_pick and pick != "auto" else None}
    ss.next_pick = "auto"
    ss.intervene_to = None      # 介入の宛先も、発言が進んだら「自動（指定なし）」に戻す


def _execute_pending(session: DebateSession) -> None:
    ss = st.session_state
    req = ss.pop("dd_pending", None)
    if not req:
        return
    state = session.state() if session.started else None
    if (len(state.messages) if state else 0) != req["nonce"] or session.finished:
        return   # 既に処理済み（連打）か、論争が閉じている
    with st.spinner("発言を生成しています…"):
        try:
            if req["action"] == "gate":
                session.run_round()
            else:
                session.step(req["speaker"])
        except Exception as e:  # Gemini の失敗など。状態は進んでいないので再試行できる
            ss.debate_error = f"{type(e).__name__}: {e}"
        else:
            ss.debate_error = None
    st.rerun()   # サイドバーなど、先に描いた部分も新しい状態で描き直す


def render(session: DebateSession, frozen: bool) -> None:
    if not frozen:
        _execute_pending(session)
    state = session.state() if session.started else None
    finished = session.finished
    nxt = session.next_node if session.started else "radar"

    # --- 操作デッキ --------------------------------------------------------
    no_data = session.ctx.fin is None
    picks = {"auto": "自動（通常順）", "growth": "Prof. Growth", "rebuild": "Dr. Rebuild", "radar": "Analyst Radar"}
    can_pick = session.can_nominate() and not frozen
    if st.session_state.get("next_pick") not in picks:
        st.session_state.next_pick = "auto"
    head, pick_col = st.columns([1.5, 1], vertical_alignment="bottom")
    with head:
        if finished:
            st.markdown(f":material/flag: **論争終了**　:gray[止まった理由：{state.stop_reason if state else ''}]")
        else:
            ph = PHASE[state.phase if state else "exploration"]
            who = PROFILES[nxt]["name"] if nxt else "—"
            rnd = f"第{state.round}ラウンド" if state else "開始前"
            why = "（ライムの介入に回答）" if state and state.reply_to else ""
            st.markdown(f":{ph['color']}-badge[{ph['icon']} {ph['label']}]　{rnd}　次の発言：**{who}**{why}")
    pick_col.selectbox("次の発言者", list(picks), format_func=picks.get, key="next_pick",
                       disabled=not can_pick or no_data, label_visibility="collapsed",
                       help="次の発言者を指名できます（探索段階のみ）。指名した担当者が割り込んで話し、"
                            "話し終えたら元の順番に戻ります。指名は1手ごとに「自動」に戻ります")
    if finished and not frozen and session.needs_comparison():
        if st.button("宣告された道を比べる（Judge）", icon=":material/compare_arrows:", type="primary"):
            with st.spinner("三つの道を同じ物差しで比べています…"):
                try:
                    session.add_comparison()
                    st.session_state.debate_error = None
                except Exception as e:
                    st.session_state.debate_error = f"{type(e).__name__}: {e}"
            st.rerun()
    if no_data:
        st.info("この回次には財務データがありません。左の資料ドックの「追加インプット」から財務書類（決算書など）を"
                "投入してください。検算を通過すると論争を始められます（根拠がなければ止まる）。", icon=":material/upload_file:")
    nonce = len(state.messages) if state else 0
    blocked = frozen or finished or no_data
    c1, c2, c3 = st.columns([1, 1, 0.6])
    c1.button("▶ 1手進める", type="primary", width="stretch", disabled=blocked, key="step_top",
              on_click=_request, args=("step", nonce, can_pick),
              help="次の担当者（または指名した担当者）の発言を一つだけ生成して止まります（Next Turn）")
    c2.button("⏩ 次のラウンドへ", width="stretch", disabled=blocked, key="gate_top",
              on_click=_request, args=("gate", nonce, can_pick),
              help="ディレクターの裁定（とフェーズ判定）まで進めて止まります（Run to Gate）")
    c3.download_button("📥 CSV", export.to_csv_bytes(state), width="stretch", key="csv_deck",
                       file_name=csv_name(session), mime="text/csv", disabled=state is None or not state.messages,
                       help="議論ログをCSVで保存（Excel でそのまま開ける BOM 付き UTF-8）")
    if st.session_state.get("debate_error"):
        st.error("発言の生成に失敗しました。状態は進んでいません。もう一度「▶ 1手進める」を押すと、同じ発言をやり直します"
                 "（「⏩ 次のラウンドへ」で進めていた場合は、そちらを押し直してください）。\n\n"
                 + st.session_state.debate_error, icon=":material/error:")

    # --- タイムライン --------------------------------------------------------
    with st.container(height=TIMELINE_HEIGHT, border=False, key="timeline", autoscroll=True):
        if state is None or not state.messages:
            st.info("論争はまだ始まっていません。「▶ 1手進める」で Analyst Radar の事実提示から始まります。",
                    icon=":material/play_circle:")
        else:
            verdicts, counted = _verdicts(state), _counted(state)
            last_round = None
            for m in state.messages:
                if m.round != last_round:
                    ph = PHASE[m.phase]["label"]
                    st.html(f'<div class="dd-round"><span>第{m.round}ラウンド・{ph}</span></div>')
                    last_round = m.round
                _card(m, verdicts, counted, state.monitor.cash_runway_months)
        if not blocked:   # 読み終えたその場で押せるよう、最新の発言の真下にも置く（上の操作デッキと同じ動き）
            who = PROFILES[nxt]["name"] if nxt else "—"
            b1, b2, _ = st.columns([1.3, 1, 0.4])
            b1.button(f"▶ 次の1手（次：{who}）", type="primary", width="stretch", key="step_bottom",
                      on_click=_request, args=("step", nonce, can_pick))
            b2.button("⏩ 次のラウンドへ", width="stretch", key="gate_bottom", on_click=_request,
                      args=("gate", nonce, can_pick))

    # --- 人間の介入 --------------------------------------------------------
    nxt_name = PROFILES[nxt]["name"] if nxt else "—"
    # 選択肢の文字は固定にする（次の発言者の名前を埋め込むと、発言が進んだあとも古い名前が表示に残る）
    targets = {None: "自動（指定なし）", "growth": "Prof. Growth に答えさせる",
               "rebuild": "Dr. Rebuild に答えさせる", "radar": "Analyst Radar に答えさせる"}
    ss = st.session_state
    if ss.pop("_reset_intervene_to", False) or ss.get("intervene_to") not in targets:
        ss.intervene_to = None
    with st.form("intervene", clear_on_submit=True, border=False):
        text = st.text_area("人間介入（ライム）", placeholder="例：いきなり8%の削減は従業員の反発で難しいのでは？／遊休地の売却は地元の反対で難しい",
                            height=80, disabled=frozen, key="intervene_text")
        c1, c2 = st.columns([1.3, 1], vertical_alignment="bottom")
        to = c1.selectbox("誰に答えさせるか", list(targets), format_func=targets.get, key="intervene_to",
                          disabled=frozen,
                          help=f"「自動」なら、次の発言者（いまは {nxt_name}）がこの介入を読んで答えます")
        sent = c2.form_submit_button("介入する", icon="👤", type="primary", width="stretch", disabled=frozen)
    st.caption((f"論争は閉じています。介入すると論争を再開し（探索に戻ります）、担当者がすぐ答えます。"
                if finished else
                f"介入すると、担当者がすぐ答えます。指名した担当者は順番を割り込んで答え、答えた後は元の順番に戻ります。"
                f"「自動」なら次の発言者（いまは {nxt_name}）が答えます"))
    if sent:
        ss["_reset_intervene_to"] = True
        was_finished = session.finished
        try:
            intervene(session, text, addressee=to)
        except EmptyInterventionError:
            st.session_state.flash = "介入の内容が空です"
            st.rerun()
        with st.spinner("介入に答える発言を生成しています…"):
            try:
                session.step()
                st.session_state.debate_error = None
            except Exception as e:
                st.session_state.debate_error = f"{type(e).__name__}: {e}"
        st.session_state.flash = ("論争を再開し、介入への答えを生成しました" if was_finished
                                  else "介入を書き込み、答えを生成しました")
        st.rerun()
