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
    if entry.kind == "財務" and entry.path is None:
        rows = digest.document_items(fin, entry.name)
        if entry.url:
            st.link_button("公開元で原本を開く", entry.url, icon=":material/open_in_new:")
        st.caption("原本はシステムに保存していません。下の表は、この書類から読み取って検算を通した科目です（出典頁付き）")
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
    with st.container(border=True, key="dock-docs"):
        entries = digest.documents(run, session.ctx, state)
        st.markdown(f"**投入済みの資料**　:gray[{len(entries)}件・名前を押すと中身を見られます]")
        if not entries:
            st.caption("まだありません")
            return
        for i, d in enumerate(entries):
            new = "　:orange-badge[途中追加]" if d.added_round else ""
            if st.button(f"{d.name}", key=f"doc_{i}", type="tertiary", icon=KIND_ICON[d.kind],
                         help=f"{d.kind}・{d.origin}"):
                _preview(d.name, run, session.ctx.fin)
            note = "" if d.citable else "・引用対象外"
            st.caption(f":{KIND_COLOR[d.kind]}-badge[{d.kind}]{new}　{d.origin}{note}")


def _gate_report(run) -> None:
    """投入資料の読み取りで検算ゲートが止まったもの（不一致の一覧）と、読み取りに失敗したもの。"""
    import json

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
        if x.get("gate") != "停止":
            continue
        rows = x.get("failed_checks") or []
        body = "".join(
            f"<tr><td>{html.escape(r['group'])}</td><td>{html.escape(r['name'])}</td><td>{r['period']}</td>"
            f"<td>{r['computed']:,}</td><td>{r['reported']:,}</td><td><b>{r['diff']:+,}</b></td><td>{r['tolerance']}</td></tr>"
            for r in rows if r.get("computed") is not None and r.get("reported") is not None)
        with st.container(border=True):
            st.warning(f"**検算不一致レポート：{x.get('file')}**　この資料の数字は論争に使っていません。"
                       "読み取り誤りか原資料の誤りかを確かめ、訂正した資料を投入してください。", icon=":material/rule:")
            if body:
                st.html('<div class="dd-cmp-wrap"><table class="dd-cmp"><thead><tr><th>区分</th><th>検算</th><th>期</th>'
                        '<th>計算値</th><th>報告値</th><th>差額</th><th>許容</th></tr></thead><tbody>'
                        + body + "</tbody></table></div>")
            else:
                st.caption("不一致の明細は記録されていません（古い読み取り記録）。財務・4P突合マトリクスの読み取り結果をご覧ください")


def _ingest(run, session: DebateSession, frozen: bool) -> None:
    ss = st.session_state
    ss.setdefault("dock_uploader", 0)
    with st.container(border=True):
        st.markdown("**追加インプット**")
        kind = st.radio("資料の種類", (QUALI, FINANCE), key="dock_kind", label_visibility="collapsed")
        if kind == QUALI:
            if frozen:
                st.caption(":material/lock: 凍結済みの回次には追加できません。最新の回次を選んでください")
            with st.form("dock_quali", clear_on_submit=True, border=False):
                name = st.text_input("資料名", placeholder="例：銀行面談メモ_10月", key="dock_name", disabled=frozen)
                text = st.text_area("本文（貼り付け）", height=100, key="dock_text", disabled=frozen,
                                    placeholder="面談の要点、現場の観察、取引先の反応など")
                files = st.file_uploader("またはテキストファイル（.md／.txt）", type=["md", "txt"],
                                         accept_multiple_files=True, key="dock_q", disabled=frozen)
                sent = st.form_submit_button("この回次に追加して議論を続ける", icon=":material/add_notes:",
                                             width="stretch", disabled=frozen)
            if sent:
                added = []
                try:
                    if (text or "").strip():
                        nm = (name or "").strip() or "追加メモ"
                        intervene(session, "", attach_name=nm, attach_text=text.strip())
                        added.append(nm)
                    for f in files or []:
                        intervene(session, "", attach_name=f.name.rsplit(".", 1)[0],
                                  attach_text=digest.decode_text(f.getvalue()))
                        added.append(f.name)
                except EmptyInterventionError:
                    pass
                ss.flash = (f"{len(added)}件の資料を追加しました。次の手から各担当者が引用できます" if added
                            else "追加する本文かファイルがありません")
                st.rerun()
            st.caption("追加した資料は出典として引用できるようになります。担当者が読むのは本文のテキストです")
        else:
            files = st.file_uploader("決算書・試算表・勘定科目内訳明細書など（PDF・Excel・画像）",
                                     type=["pdf", "xlsx", "xls", "csv", "png", "jpg", "jpeg"],
                                     accept_multiple_files=True, key=f"dock_f_{ss.dock_uploader}")
            latest_seq = run.meta.seq
            st.caption(":material/info: 財務書類は読み取り（Gemini）と検算ゲートにかけます。"
                       + ("第1次分析を凍結して第2次分析を開き、" if latest_seq == 1 else "")
                       + "論争はその回次で最初から始まります")
            if st.button("財務書類を投入する", icon=":material/upload_file:", width="stretch", key="dock_fin"):
                if not files:
                    ss.flash = "投入するファイルを選んでください"
                else:
                    target = None
                    opened = None
                    for f in files:
                        target, _, op = mock_engine.handle_upload(run.company, f.name, f.getvalue())
                        opened = opened or (target.meta.label if op else None)
                    ss[f"run_select__{run.company}"] = target.run_id
                    from session import forget

                    forget(target)   # 財務データを採用したら、論争の文脈を読み直す
                    ss.dock_uploader += 1
                    ss.flash = (f"{opened}を開き、" if opened else "") + f"{len(files)}件を{target.meta.label}に保存しました"
                st.rerun()


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
