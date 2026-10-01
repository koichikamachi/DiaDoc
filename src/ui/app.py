"""DiaDoc（ディアドック） | Dialectic-BizDoctor のUI。

起動（プロジェクトのルートで）:
    streamlit run src/ui/app.py

- 企業と分析回次（Run）は data/companies/ から読み込む。過去の回次は凍結され、当時の状態をそのまま再現する
- 論争は LangGraph（core.graph）。1手ずつ進め、回次フォルダの checkpoints.sqlite に保存する
- 画面は3ペインのコックピット：左＝資料ドック、中央＝発言タイムラインと操作デッキ、右＝ライブ・メトリクス
"""

from __future__ import annotations

import os

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import streamlit as st  # noqa: E402

import config  # noqa: E402
import theme  # noqa: E402
from agents_profile import PHASE  # noqa: E402
from components import debate, dock, live_panel, matrix, timeline, tree  # noqa: E402
from core import conclusion, digest, export, mock_engine  # noqa: E402
from core.guardrails import reconcile  # noqa: E402
from core.runs import Run, list_companies, list_runs, load_benchmarks  # noqa: E402
from session import get_session, reset  # noqa: E402

st.set_page_config(page_title="DiaDoc | Dialectic-BizDoctor", page_icon=":material/stethoscope:", layout="wide")
theme.inject()



# ---------------------------------------------------------------------------
# コールバック
# ---------------------------------------------------------------------------
def run_key(company: str) -> str:
    """回次の選択欄は企業ごとに別の部品にする（企業を替えたとき、前の企業の回次の表示が残らないように）。"""
    return f"run_select__{company}"


def _current_run() -> Run:
    ss = st.session_state
    return Run(ss.company, ss[run_key(ss.company)])


def _on_new_company() -> None:
    from core.runs import create_company

    ss = st.session_state
    try:
        company = create_company(ss.get("nc_name", ""), ss.get("nc_industry", ""), ss.get("nc_fictional", False),
                                 ss.get("nc_mission", ""))
    except (ValueError, FileExistsError) as e:
        ss.new_company_error = str(e)
        return
    ss.new_company_error = None
    ss.company = company
    ss.flash = "新しい対象会社を作りました。資料ドックから財務書類を投入してください"


def _on_rename_company() -> None:
    from core.runs import rename_company

    ss = st.session_state
    try:
        rename_company(ss.company, ss.get(f"rn_name_{ss.company}", ""), ss.get(f"rn_fictional_{ss.company}"))
    except (ValueError, FileNotFoundError) as e:
        ss.rename_error = str(e)
        return
    ss.rename_error = None
    ss.flash = "会社名を変えました（会社のIDとこれまでの記録はそのままです）"


def _on_new_run() -> None:
    ss = st.session_state
    run = mock_engine.start_manual_run(ss.company)
    ss[run_key(ss.company)] = run.run_id
    ss.flash = f"{run.meta.label}を開始しました（前の回次は凍結）"


# ---------------------------------------------------------------------------
# サイドバー（案件・回次の選択と設定だけ）
# ---------------------------------------------------------------------------
def sidebar() -> tuple[Run, str]:
    ss = st.session_state
    with st.sidebar:
        st.markdown(f"### :material/stethoscope: {config.APP_SHORT}")
        st.caption(config.APP_TAGLINE)

        companies = list_companies()
        if not companies:
            st.error("data/companies に企業がありません")
            st.stop()
        names = {c["dir"]: c.get("display_name", c["dir"]) for c in companies}
        st.selectbox("対象企業", list(names), format_func=names.get, key="company")
        with st.popover("＋ 新しい対象会社", icon=":material/add_business:", width="stretch"):
            with st.form("new_company", clear_on_submit=False, border=False):
                st.text_input("会社名", key="nc_name", placeholder="例：株式会社サンプル精工")
                st.text_input("業種", key="nc_industry", placeholder="例：金属製品製造（プレス部品）")
                st.checkbox("架空モデル（実在の会社ではない）", key="nc_fictional")
                st.text_input("診断ミッション", key="nc_mission", placeholder="資金ショートの回避と持続的再建方針の策定",
                              help="空欄なら既定のミッションになります")
                st.form_submit_button("作成する", type="primary", on_click=_on_new_company)
            if ss.get("new_company_error"):
                st.markdown(f":red[{ss.new_company_error}]")
            st.caption("第1次分析（未開始）が作られます。最初の財務書類は、次の回次を開かずに第1次分析に入ります")
        cur = next((c for c in companies if c["dir"] == ss.company), {})
        with st.popover("名前を変える", icon=":material/edit:", width="stretch"):
            with st.form(f"rename_{ss.company}", clear_on_submit=False, border=False):
                st.text_input("会社名", value=cur.get("name", ""), key=f"rn_name_{ss.company}")
                st.checkbox("架空モデル（実在の会社ではない）", value=bool(cur.get("fictional")), key=f"rn_fictional_{ss.company}")
                st.form_submit_button("変更する", type="primary", on_click=_on_rename_company)
            if ss.get("rename_error"):
                st.markdown(f":red[{ss.rename_error}]")
            st.caption(f"会社のID（{cur.get('company_id') or ss.company.split('_', 1)[0]}）と、これまでの回次・論争・資料はそのままです。"
                       "変える前の名前は記録に残ります")

        runs = list_runs(ss.company)
        ids = [r.run_id for r in runs]
        rk = run_key(ss.company)
        pending = ss.pop("pending_run_switch", None)   # 資料投入で開いた回次（選択欄を作る前にだけ書き換えられる）
        if pending and pending[0] == ss.company and pending[1] in ids:
            ss[rk] = pending[1]
        if ss.get(rk) not in ids:
            ss[rk] = ids[-1]
        labels = {r.run_id: f"{conclusion.run_heading(r, digest.load_state(r))}　{r.meta.as_of}" for r in runs}
        st.selectbox("分析回次", ids, format_func=labels.get, key=rk)
        run = _current_run()
        st.button("＋ 新しい分析回次（Run）を開始", width="stretch", on_click=_on_new_run,
                  help="最新の回次を凍結し、その状態を引き継いだ次の回次を開きます")
        with st.popover("この回次の論争をやり直す", icon=":material/restart_alt:", width="stretch",
                        disabled=run.frozen):
            st.caption("論争の途中状態と発言生成の記録を消して、最初から始めます。投入した資料は残ります")
            if st.button("やり直す", type="primary", key="reset_debate"):
                reset(run)
                ss.flash = f"{run.meta.label}の論争を最初からやり直します"
                st.rerun()
        real = st.toggle("実質BSで見る", value=False,
                         help="オフ：名目BS（帳簿どおり）　オン：実質BS（帳簿＋実質化の調整）")

        st.divider()
        read_eng = f"Gemini（{config.gemini_model()}）" if config.extractor_mode() == "gemini" else "モック"
        talk_eng = f"Gemini（{config.gemini_model()}）" if config.debate_mode() == "gemini" else "台本（モック）"
        st.caption(f":material/description: 読み取り：{read_eng}  \n:material/forum: 発言の生成：{talk_eng}")
        if os.environ.get("DBD_SESSION_SANDBOX") == "1":
            st.caption(":material/science: 公開デモ：このブラウザ専用の作業場所で動いています。ほかの人の操作とは混ざらず、"
                       "時間がたつかサーバーが再起動すると見本の状態に戻ります")
        sess = get_session(run)
        stt = sess.state() if sess.started else None
        st.download_button("📥 議論ログをCSV出力", export.to_csv_bytes(stt), width="stretch", key="csv_side",
                           file_name=timeline.csv_name(sess), mime="text/csv",
                           disabled=stt is None or not stt.messages)
        try:   # 押した時点の回次の全データから、診断レポートを組み立てる（論争の途中なら途中経過として）
            report = mock_engine.report_markdown(run)
        except Exception:   # 組み立てに失敗しても、保存済みのレポートがあればそれを出す
            report = run.read_text(f"report_v{run.meta.seq}.md")
        if report:
            st.download_button("レポートを保存（Markdown）", report, file_name=f"{run.company}_{run.run_id}_report.md",
                               mime="text/markdown", width="stretch", icon=":material/download:", key="report_md",
                               help="回次の全データ（診断適格性・前提と人間の確定・採択された施策・残るリスク・宿題）を"
                                    "まとめた診断レポート。論争が終わる前に押すと、その時点の途中経過になります")
        done = conclusion.finished(stt)
        if st.button("📝 診断経緯の文章化", width="stretch", key="narrative_btn", disabled=not done,
                     help=("診断レポートを材料に、Gemini が「審理経緯レポート（社内・監査向け）」と"
                           "「金融機関提出用サマリー」の下書きを書きます。Word（.docx）か Markdown で保存できます"
                           if done else "論争が終わった（診断完了の）回次でだけ使えます")):
            _narrative_dialog(run)
    return run, "real" if real else "nominal"


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------
def _diff_banner(run: Run) -> None:
    d = mock_engine.diff_from_parent(run)
    if d is None:
        return
    changed = "、".join(f"{c['id']} {c['item']}（{c['from']}→{c['to']}）" for c in d["changed_requests"]) or "変化なし"
    st.info(
        f"**前回（{d['parent_label']}）からの差分**　追加資料 {len(d['inputs'])} 件　／　宿題の変化：{changed}　／　"
        f"未解決のデータ請求 {len(d['open_requests'])} 件",
        icon=":material/difference:",
    )
    md_text = run.read_text("diff_summary.md") or mock_engine.diff_markdown(d)
    with st.expander("差分の詳細"):
        st.markdown(md_text)


def _header(run: Run, company: dict, state, base=None) -> None:
    meta = run.meta
    done = conclusion.finished(state)
    ph = PHASE[state.phase] if state and state.messages and not done else None   # 進行中だけフェーズを添える
    st.html(f'<div class="dd-header"><span class="dd-brand">{config.APP_SHORT}<small>Dialectic-BizDoctor</small></span>'
            f'<span class="dd-tagline">{config.APP_TAGLINE}</span></div>')
    chips = (f":material/business: **{company.get('display_name', run.company)}**　｜　"
             f"**{conclusion.run_heading(run, state, base)}**　:gray[{meta.as_of}]")
    if ph:
        chips += f"　｜　:{ph['color']}-badge[{ph['icon']} {ph['label']}]"
    if company.get("fictional"):
        chips += "　:violet-badge[:material/theater_comedy: 架空モデル]"
    elif company.get("anonymized"):
        chips += "　:violet-badge[:material/masks: モデル企業]"
    st.markdown(chips)


@st.dialog("診断経緯の文章化", width="large")
def _narrative_dialog(run: Run) -> None:
    """構造化レポートから報告書の下書きを作り、読む・コピーする・保存する。材料が同じなら作り直さない。"""
    from core import narrative
    from core.docx_export import markdown_to_docx

    ss = st.session_state
    report = mock_engine.report_markdown(run)
    nar = narrative.load(run)
    regen = ss.pop("narrative_regen", False)
    if regen or nar is None or nar.report_hash != narrative.report_hash(report):
        engine = f"Gemini（{config.gemini_model()}）" if config.debate_mode() == "gemini" else "モック"
        with st.spinner(f"{engine}で文章を書いています（数十秒かかることがあります）…"):
            try:
                nar = narrative.generate(run, report=report)
            except Exception as e:   # 生成の失敗は画面に出し、診断の記録は変えない
                st.error(f"文章化に失敗しました。もう一度「📝 診断経緯の文章化」を押してください。\n\n{type(e).__name__}: {e}",
                         icon=":material/error:")
                return
    st.caption(f"生成：{nar.engine}　{nar.generated_at}　材料：この回次の診断レポート（指紋 {nar.report_hash}）")
    st.warning(narrative.DRAFT_NOTE, icon=":material/edit_note:")
    if nar.unverified_numbers:
        st.error("材料のレポートにない数字が本文にあります（要確認）：" + "、".join(nar.unverified_numbers),
                 icon=":material/rule:")
    else:
        st.caption(":material/verified: 数字の照合：本文の数字はすべて材料のレポートにあります")
    doc = nar.document()
    base = f"{run.company}_{run.run_id}_診断経緯"
    c1, c2, c3 = st.columns(3)
    try:
        docx_bytes = markdown_to_docx(doc, f"{run.meta.label} 診断経緯（下書き）")
    except ImportError:   # python-docx が入っていない環境
        docx_bytes = None
        c1.caption("Word で保存するには python-docx が必要です（pip install python-docx）")
    if docx_bytes is not None:
        c1.download_button("Word（.docx）で保存", docx_bytes, file_name=f"{base}.docx", width="stretch",
                           icon=":material/description:", key="nar_docx",
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    c2.download_button("Markdown（.md）で保存", doc, file_name=f"{base}.md", mime="text/markdown", width="stretch",
                       icon=":material/download:", key="nar_md")
    if c3.button("作り直す", width="stretch", icon=":material/refresh:", key="nar_regen"):
        ss.narrative_regen = True
        st.rerun(scope="fragment")
    t1, t2 = st.tabs(["読む", "コピー用（右上のボタンで全文をコピー）"])
    with t1:
        st.markdown(nar.text)
    with t2:
        st.code(doc, language="markdown", wrap_lines=True)


def _goal_banner(run: Run, session, state) -> None:
    """論争が終わったら、結論を一目で分かるカード（ゴールテープ）を画面の上に出す。"""
    if not conclusion.finished(state) or session.ctx.fin is None:
        return
    b = conclusion.banner(state, session.ctx.base, run.read("data_requests.json", []))
    if b is None:
        return
    body = f"**{b.title}**" + "".join(f"\n- {x}" for x in b.lines)
    show = {"success": st.success, "info": st.info, "warning": st.warning, "error": st.error}[b.tone]
    with st.container(key="goal-banner"):
        show(body, icon=b.icon)


def _adoption(session, state, run: Run) -> None:
    """人間が選んだ道を「採択」として記録する（論争の中身は変えない）。"""
    tri = digest.triage(state)
    if tri is None:
        return
    with st.container(border=True):
        st.markdown("**採択の記録**　:gray[経営者・金融機関との協議で選んだ道を残します]")
        if state.adopted_option:
            st.success(f"採択：{state.adopted_option}" + (f"　（{state.adopted_note}）" if state.adopted_note else ""),
                       icon=":material/verified:")
        if run.frozen:
            st.caption(":material/lock: 凍結済みの回次では記録を変えられません")
            return
        names = [o.name for o in tri.options]
        c1, c2 = st.columns([1.2, 1])
        pick = c1.selectbox("採る道", names, key="adopt_pick")
        note = c2.text_input("理由・条件（任意）", key="adopt_note", placeholder="例：メインバンクが3か月の猶予に応諾")
        if st.button("この道を採択として記録", key="adopt_btn", icon=":material/how_to_vote:"):
            session.adopt(pick, note)
            st.session_state.flash = f"採択を記録しました：{pick}"
            st.rerun()


def _run_comparison(run: Run) -> None:
    """同じ会社の分析回次の結論を横に並べる。"""
    import pandas as pd

    runs = list_runs(run.company)
    st.markdown("##### 分析回次の比較")
    if len(runs) < 2:
        st.info("比べる回次がまだありません。サイドバーの「＋ 新しい分析回次（Run）を開始」で第2次分析を開くと、"
                "同じ資料から論争をやり直した結果を、ここで第1次と並べて比べられます。", icon=":material/compare:")
    labels = {r.run_id: f"{r.meta.label}（{r.meta.as_of}）" for r in runs}
    picked = st.multiselect("比べる回次", list(labels), default=[r.run_id for r in runs][-3:],
                            format_func=labels.get, key=f"cmp_runs__{run.company}__{len(runs)}", max_selections=4)
    chosen = [r for r in runs if r.run_id in picked]
    if not chosen:
        return
    rows = digest.compare_runs(chosen)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"物差し": st.column_config.TextColumn(width="small")})
    st.caption("残余月数は「改善前 → 通過した改善を反映した値」。凍結した回次は、当時の状態をそのまま読み出しています")


def main() -> None:
    run, mode = sidebar()
    ss = st.session_state
    company = next((c for c in list_companies() if c["dir"] == ss.company), {})
    session = get_session(run)
    state = session.state() if session.started else None

    _header(run, company, state, session.ctx.base if session.ctx.fin is not None else None)
    if company.get("fictional"):
        st.warning("**架空モデル**：実在の会社ではありません。資金ショート寸前の窮境企業として作った対比用のシナリオです。",
                   icon=":material/theater_comedy:")
    elif company.get("anonymized"):
        st.info("**モデル企業**：実在企業の公開資料をもとに、財務の構造を保ったまま全数値を一定の係数で変換したものです。"
                "実在企業の決算書の数値そのものではありません。", icon=":material/masks:")
    if ss.get("flash"):
        st.toast(ss.flash, icon=":material/record_voice_over:")
        ss.flash = None
    _goal_banner(run, session, state)
    if run.frozen:
        st.info(f"この回次は {run.meta.frozen_at} に凍結されました。当時の論争・検算・ツリーをそのまま再現しています。",
                icon=":material/lock:")
    _diff_banner(run)

    fin = run.financials()
    if fin is not None and not run.frozen:
        mock_engine.ensure_debt_request(run)   # 約定返済が確かめられなければ、返済予定表を必須の宿題として請求（一件だけ）
    src_run = run.financials_source()
    report = reconcile(fin) if fin else None
    source_label = "—" if src_run is None else (
        "この回次の投入資料" if src_run.run_id == run.run_id else f"{src_run.meta.label}で投入された財務データを引き継ぎ")

    t1, t2, t3, t4 = st.tabs([":material/forum: 論争コックピット", ":material/table_chart: 財務・4P突合マトリクス",
                              ":material/account_tree: 意思決定ツリー", ":material/compare: 回次の比較"])
    with t1:
        with st.container(key="cockpit"):
            left, center, right = st.columns([0.22, 0.48, 0.30], gap="medium")
            with left, st.container(key="pane-left"):
                dock.render(run, session, state)
            with center, st.container(key="pane-center"):
                st.markdown('<div class="dd-pane-title">対話タイムライン</div>', unsafe_allow_html=True)
                timeline.render(session, run.frozen)
            with right, st.container(key="pane-right"):
                live_panel.render(fin, state, session.ctx.base, session.ctx.adjustments)
    with t2:
        matrix.render(fin, report, mode, load_benchmarks(run.company), run.read("data_requests.json", []), source_label,
                      run=run, session=session)
        matrix.render_extractions(run)
    with t3:
        tree.render_live(state, session.ctx.mission)
        st.divider()
        cmp_ = digest.comparison(state)
        if cmp_ is not None:
            st.markdown("##### Level 0 の道の比較")
            st.caption("Moderator Judge が同じ物差しで並べたもの。「道筋がつくまで」の✓✕は、残余月数と比べてプログラムが判定しています。"
                       "どれを選ぶかは経営者と金融機関が決めます")
            st.html(timeline.comparison_html(cmp_, state.monitor.cash_runway_months))
            st.markdown(cmp_.text.replace("\n", "  \n"))
            _adoption(session, state, run)
            st.divider()
        legacy_tree = run.read("decision_tree.json")
        if legacy_tree:
            with st.expander("（参考）旧・静的ツリー", icon=":material/history:"):
                st.caption("LangGraph 接続前の台本で作ったツリーです。上の論争とは連動しません。")
                tree.render(legacy_tree)
    with t4:
        _run_comparison(run)

    legacy = run.read("debate_log.json", [])
    if legacy:
        st.divider()
        with st.expander("（参考）旧・静的分析ログ", icon=":material/history:"):
            st.caption("LangGraph 接続前の台本による論争の記録です。現在の論争コックピットとは連動しません。")
            debate.render(legacy, run.read("constraints.json", {}))


main()
