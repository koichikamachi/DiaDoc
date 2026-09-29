"""左ペイン：資料ドック（投入済みの資料、追加インプット、検討ステータス）。

追加インプットの規則（CLAUDE.md 決定事項）：
- ヒアリングメモ等の定性資料・テキスト → 今の回次に追加し、議論を続ける（次の手から引用できる）
- 決算書など検算を伴う財務書類 → 従来どおり次の回次を開いて新規に始める
"""

from __future__ import annotations

import html

import streamlit as st

from agents_profile import PHASE
from core import digest, mock_engine
from core.graph import DebateSession
from core.interrupt import EmptyInterventionError, intervene
from state import DebateState

KIND_ICON = {"財務": ":material/account_balance:", "定性": ":material/description:", "検算表": ":material/table_view:",
             "資料": ":material/attach_file:"}
KIND_COLOR = {"財務": "blue", "定性": "green", "検算表": "violet", "資料": "gray"}
QUALI = "定性資料（この回次に追加して議論を続ける）"
FINANCE = "財務書類（検算あり。次の回次を開いて新規に始める）"


@st.dialog("資料のプレビュー", width="large")
def _preview(entry_name: str, run, fin) -> None:
    """資料の中身をその場で確かめる。原本のない出典書類は、読み取った科目の表と公開元のリンクを出す。"""
    import pandas as pd

    entry = next((d for d in digest.documents(run, _ctx_of(run), None) if d.name == entry_name), None)
    if entry is None:
        st.warning("資料が見つかりません")
        return
    st.markdown(f"**{entry.name}**　:gray[{entry.kind}・{entry.origin}]")
    rows = digest.document_items(fin, entry.name) if entry.kind == "財務" else []
    if entry.kind == "財務" and (entry.path is None or rows):
        if entry.url:
            st.link_button("公開元で原本を開く", entry.url, icon=":material/open_in_new:")
        if entry.path is None:
            st.caption("原本はシステムに保存していません。下の表は、この書類から読み取って検算を通した科目です（出典頁付き）")
        else:
            st.caption("下の表は、この書類から読み取って検算を通した科目です（出典頁付き）")
            st.download_button("原本を保存", entry.path.read_bytes(), file_name=entry.path.name,
                               icon=":material/download:")
        if rows:
            df = pd.DataFrame(rows).drop(columns=["key"])
            st.dataframe(df, hide_index=True, width="stretch", height=460,
                         column_config={"前期": st.column_config.NumberColumn(format="localized"),
                                        "当期": st.column_config.NumberColumn(format="localized")})
        return
    p = entry.path
    data = p.read_bytes()
    suffix = p.suffix.lower()
    if suffix in (".md", ".txt"):
        with st.container(height=480, border=True):
            st.markdown(digest.decode_text(data))
    elif suffix in (".xlsx", ".xls"):
        try:
            sheets = pd.read_excel(p, sheet_name=None, header=None)
            name = st.selectbox("シート", list(sheets))
            st.dataframe(sheets[name].head(200), width="stretch", height=440)
        except Exception as e:  # 壊れたファイルでも画面は落とさない
            st.warning(f"Excel を表示できません（{type(e).__name__}）")
    elif suffix == ".csv":
        st.code(digest.decode_text(data)[:6000])
    elif suffix in (".png", ".jpg", ".jpeg"):
        st.image(data)
    else:
        st.caption("この形式は画面の中では表示できません。保存して開いてください")
    st.download_button("ファイルを保存", data, file_name=p.name, icon=":material/download:")


def _ctx_of(run):
    from session import get_session

    return get_session(run).ctx


def _docs(run, session: DebateSession, state: DebateState | None) -> None:
    ss = st.session_state
    with st.container(border=True, key="dock-docs"):
        entries = digest.documents(run, session.ctx, state)
        st.markdown(f"**投入済みの資料**　:gray[{len(entries)}件・名前を押すと中身を見られます]")
        if not entries:
            st.caption("まだありません")
            return
        for i, d in enumerate(entries):
            new = "　:orange-badge[途中追加]" if d.added_round else ""
            name_col, del_col = st.columns([6, 1], vertical_alignment="center", gap="small")
            with name_col:
                if st.button(f"{d.name}", key=f"doc_{i}", type="tertiary", icon=KIND_ICON[d.kind],
                             help=f"{d.kind}・{d.origin}"):
                    _preview(d.name, run, session.ctx.fin)
            ok, why = mock_engine.withdrawable(run, d.path)
            if d.path is not None and d.path.parent == run.path / "inputs":   # この回次に置かれたファイルだけ屑かごを出す
                with del_col:
                    with st.popover("", icon=":material/delete:", disabled=not ok,
                                    help="この資料を取り下げる" if ok else why, key=f"withdraw_pop_{i}"):
                        st.markdown(f"**「{d.name}」を取り下げますか？**")
                        st.caption("ファイルは消さずに回次の中の保管場所へ移し、監査証跡に記録します。"
                                   "以後は引用できなくなりますが、これまでの発言の記録は残ります")
                        if st.button("取り下げる", key=f"withdraw_{i}", type="primary", icon=":material/delete:"):
                            from session import forget

                            try:
                                ss.flash = mock_engine.withdraw_input(run, d.path.name)
                            except ValueError as e:
                                ss.flash = str(e)
                            forget(run)   # 引用できる資料を読み直す
                            st.rerun()
            note = "" if d.citable else "・引用対象外"
            st.caption(f":{KIND_COLOR[d.kind]}-badge[{d.kind}]{new}　{d.origin}{note}")


def _names(files) -> str:
    """選んだファイル名をボタンに入れる形にする（2件以上は「ほかN件」）。"""
    files = list(files or [])
    return f"「{files[0].name}」" + (f"ほか{len(files) - 1}件" if len(files) > 1 else "")


GUIDE = ":material/looks_one: 資料を選択　─►　:material/looks_two: 下のボタンで確定投入"


def _failed_table(rows: list[dict]) -> None:
    body = "".join(
        f"<tr><td>{html.escape(r['group'])}</td><td>{html.escape(r['name'])}</td><td>{r['period']}</td>"
        f"<td>{r['computed']:,}</td><td>{r['reported']:,}</td><td><b>{r['diff']:+,}</b></td><td>{r['tolerance']}</td></tr>"
        for r in rows if r.get("computed") is not None and r.get("reported") is not None)
    if body:
        st.html('<div class="dd-cmp-wrap"><table class="dd-cmp"><thead><tr><th>区分</th><th>検算</th><th>期</th>'
                '<th>計算値</th><th>報告値</th><th>差額</th><th>許容</th></tr></thead><tbody>' + body + "</tbody></table></div>")
    else:
        st.caption("不一致の明細は記録されていません（古い読み取り記録）。財務・4P突合マトリクスの読み取り結果をご覧ください")


def _dropped(x: dict, hint: str) -> None:
    """読み取りで標準科目に当てはめられず、金額ごと捨てた行。検算の不一致・未確認の原因になりうる。"""
    rows = ((x.get("report") or {}).get("dropped_values")) or []
    if not rows:
        return
    body = "".join(f"<tr><td>{html.escape(r.get('section') or '')}</td><td>{html.escape(r.get('label') or '')}</td>"
                   f"<td>{'' if r.get('prev') is None else format(r['prev'], ',')}</td>"
                   f"<td>{'' if r.get('cur') is None else format(r['cur'], ',')}</td></tr>" for r in rows)
    st.markdown(f"**読み取れなかった行（金額あり・{len(rows)}件）**")
    st.html('<div class="dd-cmp-wrap"><table class="dd-cmp"><thead><tr><th>区分</th><th>原資料の科目名</th><th>前期</th>'
            '<th>当期</th></tr></thead><tbody>' + body + "</tbody></table></div>")
    st.caption(hint)


def _gate_report(run) -> None:
    """投入資料の検算ゲートの結果。軽微な差異は人が「差し替え」か「端数調整で続行」を選ぶ。重大な差異は止める。"""
    import json

    ss = st.session_state
    d = run.path / "extracted"
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            x = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if x.get("error"):
            st.error(f"**{x.get('file')}** の読み取りに失敗しました。資料は保存済みです。\n\n{x['error'][:300]}",
                     icon=":material/error:")
            continue
        gate, m, name = x.get("gate"), x.get("materiality") or {}, x.get("file", "")
        head = m.get("headline", "")
        if gate == "軽微":
            with st.container(border=True):
                st.warning(f"**{name}**：軽微な計算差異（{head}）を検出しました。"
                           "財務諸表を差し替えるか、端数調整で続行するかを選んでください。選ぶまで、この資料の数値は論争に使いません。",
                           icon=":material/rule:")
                _failed_table(x.get("failed_checks") or [])
                c1, c2 = st.columns(2)
                key = f.stem
                if c1.button("財務諸表を修正して差し替える", key=f"gate_replace_{key}", width="stretch",
                             disabled=run.frozen):
                    ss.flash = mock_engine.choose_replace(run, name)
                    st.rerun()
                if c2.button("端数調整で自動調整して診断を続行する", key=f"gate_adjust_{key}", type="primary",
                             width="stretch", disabled=run.frozen):
                    from session import forget

                    try:
                        ss.flash = mock_engine.approve_rounding(run, name)
                    except ValueError as e:
                        ss.flash = str(e)
                    forget(run)   # 採用した財務データで論争の文脈を読み直す
                    st.rerun()
                st.caption("端数調整：書類に書かれた合計を正として残し、内訳とのずれを「端数調整差額」として計上します"
                           "（BS の資産側はその他流動資産、負債・純資産側はその他流動負債、PL は雑損益）。承認は監査証跡に記録します")
        elif gate == "停止":
            with st.container(border=True):
                st.error(f"**{name}**：重大な計算不一致（{head}）のため、診断プロセスを停止しました。"
                         "誤ったトリアージ判定を防ぐため、元資料の数値を訂正のうえ再投入してください。", icon=":material/block:")
                if m.get("reasons"):
                    st.caption("重大と判定した理由：" + "／".join(m["reasons"]))
                _failed_table(x.get("failed_checks") or [])
                _dropped(x, "不一致は、元資料の誤りではなく、これらの行を読み取れなかったことによる可能性があります")
        elif gate == "未確認":
            with st.container(border=True):
                st.error(f"**{name}**：中心となる検算（{'・'.join(m.get('unverified_core', []))}）を確かめられないため、"
                         "診断プロセスを停止しました。確かめていない数値で論争を始めることはしません。", icon=":material/help:")
                _dropped(x, "資料を補うか、読み取れる形（科目名の書き方など）に直して再投入してください")
        elif gate == "差し替え待ち":
            st.info(f"**{name}**：差し替えを選びました。訂正した財務諸表を投入してください（この資料は採用していません）。",
                    icon=":material/sync:")
    log = run.read("audit_log.json", [])
    if log:
        with st.expander(f"監査証跡（{len(log)}件）", icon=":material/fact_check:"):
            for e in reversed(log):
                st.markdown(f"- {e['at']}　{e['actor']}：{e['action']}（{e.get('file', '')}）"
                            + (f"　{e['headline']}" if e.get("headline") else ""))
                for line in e.get("entries", []):
                    st.caption(f"　　{line}")


def _ingest(run, session: DebateSession, frozen: bool) -> None:
    ss = st.session_state
    ss.setdefault("dock_uploader", 0)
    n = ss.dock_uploader   # 投入のたびに増やし、入力欄を空に戻す
    with st.container(border=True, key="dock-ingest"):
        st.markdown("**追加インプット**")
        kind = st.radio("資料の種類", (QUALI, FINANCE), key="dock_kind", label_visibility="collapsed")
        if kind == QUALI:
            if frozen:
                st.caption(":material/lock: 凍結済みの回次には追加できません。最新の回次を選んでください")
            name = st.text_input("資料名", placeholder="例：銀行面談メモ_10月", key=f"dock_name_{n}", disabled=frozen)
            text = st.text_area("本文（貼り付け）", height=100, key=f"dock_text_{n}", disabled=frozen,
                                placeholder="面談の要点、現場の観察、取引先の反応など")
            st.caption(GUIDE)
            files = st.file_uploader("またはテキストファイル（.md／.txt）", type=["md", "txt"],
                                     accept_multiple_files=True, key=f"dock_q_{n}", disabled=frozen)
            has_text = bool((text or "").strip())
            if files:
                label = f"📝 選択した{_names(files)}をこの回次に追加投入"
            elif has_text:
                label = f"📝 貼り付けた本文「{(name or '').strip() or '追加メモ'}」をこの回次に追加投入"
            else:
                label = "上の枠でファイルを選択するか、本文を貼り付けてください"
            ready = bool(files) or has_text
            if st.button(label, key="dock_quali_send", width="stretch", type="primary" if ready else "secondary",
                         disabled=frozen or not ready):
                added = []
                try:
                    if has_text:
                        nm = (name or "").strip() or "追加メモ"
                        intervene(session, "", attach_name=nm, attach_text=text.strip())
                        added.append(nm)
                    for f in files or []:
                        intervene(session, "", attach_name=f.name.rsplit(".", 1)[0],
                                  attach_text=digest.decode_text(f.getvalue()))
                        added.append(f.name)
                except EmptyInterventionError:
                    pass
                ss.dock_uploader += 1
                ss.flash = (f"{len(added)}件の資料を追加しました。次の手から各担当者が引用できます" if added
                            else "追加する本文かファイルがありません")
                st.rerun()
            st.caption("追加した資料は出典として引用できるようになります。担当者が読むのは本文のテキストです")
        else:
            st.caption(GUIDE)
            files = st.file_uploader("決算書・試算表・勘定科目内訳明細書など（PDF・Excel・画像・テキスト）",
                                     type=["pdf", "xlsx", "xls", "csv", "png", "jpg", "jpeg", "txt", "md"],
                                     accept_multiple_files=True, key=f"dock_f_{n}")
            latest_seq = run.meta.seq
            if not files:
                label = "上の枠でファイルを選択してください"
            elif mock_engine.opens_new_run(run.company):
                label = f"📄 選択した{_names(files)}を投入して新回次を開始"
            else:
                from core.runs import latest_run

                label = f"📄 選択した{_names(files)}を{latest_run(run.company).meta.label}に投入"
            if st.button(label, width="stretch", key="dock_fin", type="primary" if files else "secondary",
                         disabled=not files):
                target = None
                opened = None
                for f in files:
                    target, _, op = mock_engine.handle_upload(run.company, f.name, f.getvalue())
                    opened = opened or (target.meta.label if op else None)
                # 回次の選択欄はこの時点で描画済みなので直接は書き換えない。次の描画の最初（選択欄を作る前）に反映する
                ss.pending_run_switch = (target.company, target.run_id)
                from session import forget

                forget(target)   # 財務データを採用したら、論争の文脈を読み直す
                ss.dock_uploader += 1
                ss.flash = (f"{opened}を開き、" if opened else "") + f"{len(files)}件を{target.meta.label}に保存しました"
                st.rerun()
            st.caption(":material/info: 財務書類は読み取り（Gemini）と検算ゲートにかけます。"
                       + ("第1次分析を凍結して第2次分析を開き、" if latest_seq == 1 else "")
                       + "論争はその回次で最初から始まります。財務データのない第1次分析には、そのまま入ります")


def _status(state: DebateState | None) -> None:
    with st.container(border=True):
        st.markdown("**検討ステータス**")
        if state is None:
            st.caption("論争は未開始です")
            return
        ph = PHASE[state.phase]
        st.markdown(f":{ph['color']}-badge[{ph['icon']} {ph['label']}]　第{state.round}ラウンド")
        if state.stop_reason:
            st.caption(f"止まった理由：{state.stop_reason}")
        if state.agenda:
            icon = {"審理中": ":material/pending:", "決着": ":material/check:", "保留": ":material/pause:"}
            st.markdown("  \n".join(f"{icon[a.status]} {a.id} {a.title}　:gray[{a.status}]" for a in state.agenda))
        tri = digest.triage(state)
        if tri is None:
            if state.phase == "triage_ready":
                st.caption("トリアージ段階に入りました。Dr. Rebuild の宣告を待っています")
            return
        st.markdown(f"**Level 0：何を残し、何を捨てるか**　:gray[第{tri.round}ラウンドの宣告]")
        st.markdown("  \n".join(f"{i}. {o.name}　:gray[前提{len(o.preconditions)}件]" for i, o in enumerate(tri.options, 1)))
        st.caption("番号は宣告の順で、優先順位ではありません。選ぶのは経営者と金融機関です")
        with st.expander("前提条件と、残すもの・捨てるもの", icon=":material/checklist:"):
            for o in tri.options:
                pre = "".join(f"<li>{html.escape(p)}</li>" for p in o.preconditions)
                st.html(f'<div class="dd-option"><div class="dd-option-name">{html.escape(o.name)}</div>'
                        f'<div><span class="dd-k">残す</span>{html.escape("・".join(o.keep) or "—")}</div>'
                        f'<div><span class="dd-k">捨てる</span>{html.escape("・".join(o.discard) or "—")}</div>'
                        f'<div class="dd-k">前提条件</div><ul class="dd-pre">{pre}</ul></div>')


MISSION_PRESETS = (
    "資金ショートの回避と持続的再建方針の策定",
    "本業の収益力の立て直し（受取配当に頼らない営業利益の確保）",
    "成長戦略の策定（成長投資と資金繰りの両立）",
    "スポンサー・提携先の選定条件の整理",
    "事業承継に向けた企業価値の改善",
)
FREE = "（自由に書く）"


def _mission(run, session: DebateSession, state: DebateState | None) -> None:
    from state import DEFAULT_MISSION

    current = state.mission if state else (session.ctx.mission or DEFAULT_MISSION)
    st.html(f'<div class="dd-mission"><div class="dd-mission-k">診断ミッション</div>'
            f'<div class="dd-mission-v">{html.escape(current)}</div></div>')
    with st.expander("ミッションを変える", icon=":material/flag:"):
        if run.frozen:
            st.caption(":material/lock: 凍結済みの回次では変えられません")
            return
        opts = list(dict.fromkeys([current, *MISSION_PRESETS])) + [FREE]
        choice = st.selectbox("主訴の型", opts, key="mission_choice")
        free = st.text_input("ミッションを書く", key="mission_free", disabled=choice != FREE,
                             placeholder="例：メインバンクへの事業計画提出に向けた再建策の骨子づくり")
        st.caption("4人の担当者に共通の討議目的になります。論争の途中で変えると、介入として記録に残ります")
        if st.button("このミッションで進める", key="mission_set", icon=":material/check:"):
            new = free if choice == FREE else choice
            try:
                session.set_mission(new)
                st.session_state.flash = f"診断ミッション：{new.strip()}"
            except ValueError as e:
                st.session_state.flash = str(e)
            st.rerun()


def render(run, session: DebateSession, state: DebateState | None) -> None:
    st.markdown('<div class="dd-pane-title">資料ドック</div>', unsafe_allow_html=True)
    _mission(run, session, state)
    _docs(run, session, state)
    _gate_report(run)
    _ingest(run, session, run.frozen)
    _status(state)
