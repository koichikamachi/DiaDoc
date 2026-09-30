"""タブ2：財務・4P突合マトリクス。

対象企業の数値は回次の financials.json から、検算は core.guardrails.reconcile の実結果を表示する。
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import mock_data as md
from core import indicators as ind
from core import metrics
from schema import Financials, ReconciliationReport

# 既定パレットの先頭3色（隣接・全組合せとも色覚多様性の検証済み）
C_COMPANY = "#2a78d6"
C_AVG = "#eb6834"
C_BENCH = "#1baf7a"

PERIOD_LABEL = {"prev": "前期", "cur": "当期"}


def _oku(v: float) -> str:
    return f"{v / 1e5:,.1f}億円"


def _unit(fin: Financials) -> tuple[float, str]:
    """表示単位は会社の規模ではなく金額の桁で決める。総資産が10億円に届かない（億円で1桁になる）ときは百万円、
    10億円以上なら億円。億円で1桁だと目盛りと区画の数字が粗くなりすぎるため（千円からの割り算の値と単位名）。"""
    return (1e3, "百万円") if (fin.value("ta") or 0) < 1_000_000 else (1e5, "億円")


def _amt(fin: Financials, v: float) -> str:
    div, name = _unit(fin)
    return f"{v / div:,.1f}{name}"


def _ratio_frame(fin: Financials, mode: str, benches: list[dict], adj=()) -> pd.DataFrame:
    rows = []
    for i in (r for r in ind.RATIOS if r.chart):
        v = ind.evaluate(fin, i, mode, adj)
        row = {"指標": i.label, "対象企業": None if v.cur is None else v.cur * 100}
        for b in benches:
            row[b["name"]] = b["ratios"].get(i.key, float("nan")) * 100
        rows.append(row)
    return pd.DataFrame(rows)


def _basis_frame(fin: Financials, mode: str, benches: list[dict], adj=()) -> pd.DataFrame:
    """グラフの基礎数値：比率ごとに計算式、分子・分母の内訳（科目・金額・出典頁）、比較値とその出典。"""
    rows = []
    for i in ind.RATIOS:
        v = ind.evaluate(fin, i, mode, adj)
        side = lambda parts: "＋".join(f"{p.label} {p.cur:,}（{p.source}）" for p in parts if p.cur is not None) or "—"
        row = {"指標": i.label, "計算式": i.formula, "分子": side(v.num), "分母": side(v.den),
               "対象企業": ind.fmt(i, v.cur)}
        if v.note:
            row["分母"] += "　※" + v.note.split("：")[0]
        for b in benches:
            val = b["ratios"].get(i.key)
            row[b["name"]] = "—" if val is None else f"{val:.1%}"
        row["比較値の出典"] = "仮置き（画面確認用。判断に使わない）" if any(b.get("placeholder") for b in benches) else \
            "、".join(b.get("source", b["name"]) for b in benches)
        rows.append(row)
    return pd.DataFrame(rows)


def _ratio_chart(df: pd.DataFrame, benches: list[dict]) -> go.Figure:
    fig = go.Figure()
    series = [("対象企業", C_COMPANY, "")] + [
        (b["name"], c, "/" if b.get("placeholder") else "") for b, c in zip(benches, (C_AVG, C_BENCH))]
    for name, color, pattern in series:
        fig.add_bar(
            y=df["指標"], x=df[name], name=name, orientation="h",
            marker=dict(color=color, opacity=1.0 if not pattern else 0.55,
                        pattern=dict(shape=pattern, fillmode="overlay", fgcolor="rgba(255,255,255,0.7)", size=6, solidity=0.25)),
            hovertemplate="%{y}<br>" + name + "：%{x:.1f}%<extra></extra>",
        )
    fig.update_layout(
        barmode="group", bargap=0.35, bargroupgap=0.08, height=430, margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis=dict(ticksuffix="%", showgrid=True, zeroline=False), yaxis=dict(autorange="reversed"),
    )
    return fig


KIND_COLOR = {"資産": C_COMPANY, "負債": C_AVG, "純資産": C_BENCH}
# 下から積む順（土台）。調整の斜線は一番上に重ね、名目と実質で土台の高さがそろうようにする
STACK_ORDER = {"資産": ["投資その他の資産", "有形・無形固定資産", "その他の流動資産", "現金預金"],
               "負債・純資産": ["純資産", "固定負債", "流動負債"]}
PATTERN = dict(fillmode="overlay", fgcolor="rgba(255,255,255,0.8)", size=7, solidity=0.3)


def _stack_key(b: metrics.BSBlock) -> tuple:
    order = STACK_ORDER[b.side]
    return (b.side != "資産", bool(b.adjust), order.index(b.label) if b.label in order else len(order))


def _bs_chart(fin: Financials, adj=()) -> go.Figure:
    """比例縮尺の貸借対照表。柱の高さが金額に比例し、名目（帳簿）と実質（帳簿＋調整）を同じ目盛りで並べる。"""
    has_adj = bool(metrics.real_adjustments(fin, adj))
    views = [("名目（帳簿）", "nominal"), ("実質（調整後）", "real")] if has_adj else [("帳簿＝実質（調整なし）", "nominal")]
    div, unit = _unit(fin)
    fig = go.Figure()
    # 凡例は固定順で先に作る（色は種類、斜線は調整）。区画ごとの名前は柱の中とホバーに出す
    legend = [("資産", KIND_COLOR["資産"], ""), ("負債", KIND_COLOR["負債"], ""), ("純資産", KIND_COLOR["純資産"], "")]
    if has_adj:
        legend.append(("斜線：調整（名目の列＝除く分／実質の列＝加わる分）", "#9a9994", "/"))
    for name, color, shape in legend:
        fig.add_bar(x=[[views[0][0]], ["資産"]], y=[None], name=name,
                    marker=dict(color=color, pattern=dict(shape=shape, **PATTERN)), hoverinfo="skip")
    for view, mode in views:
        blocks = metrics.bs_blocks(fin, mode, adj)
        for b in sorted(blocks, key=_stack_key):
            what = f"調整（{b.adjust}）：{b.label}" if b.adjust else b.label
            neg = b.kind == "純資産" and b.amount < 0
            fig.add_bar(
                x=[[view], [b.side]], y=[b.amount / div], name=what, showlegend=False,
                marker=dict(color=KIND_COLOR[b.kind], line=dict(width=2, color="rgba(255,255,255,0.85)"),
                            opacity=0.5 if b.adjust else 1.0, pattern=dict(shape="/" if b.adjust or neg else "", **PATTERN)),
                text=f"{'債務超過 ' if neg else ''}{what}<br>{b.amount / div:,.1f}{unit}", textposition="inside",
                insidetextanchor="middle",
                hovertemplate=f"{view}・{b.side}<br>{what}<br>{b.amount:,}千円<extra></extra>",
            )
    fig.update_layout(
        barmode="relative", bargap=0.08, bargroupgap=0.0, height=520, margin=dict(l=10, r=10, t=10, b=10),
        uniformtext=dict(minsize=10, mode="hide"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, traceorder="normal"),
        yaxis=dict(ticksuffix=unit, showgrid=True, zeroline=True), xaxis=dict(type="multicategory"),
    )
    return fig


def _bs_caption(fin: Financials, adj=()) -> str:
    nom, real = metrics.balance_sheet(fin, "nominal"), metrics.balance_sheet(fin, "real", adj)
    if not metrics.real_adjustments(fin, adj):
        head = ("実質化の調整はまだありません。帳簿どおりに描いています"
                "（株式や土地は取得原価で計上されている前提。含み損益は外からは分からないため）。")
    else:
        head = (f"帳簿の総資産{_amt(fin, nom['総資産'])}は、調整を加えると{_amt(fin, real['総資産'])}、"
                f"純資産は{_amt(fin, nom['純資産'])}から{_amt(fin, real['純資産'])}になります（推計。税効果は入力どおり）。")
    if real["純資産"] < 0:
        head += f"実質の純資産はマイナス（債務超過 {_amt(fin, -real['純資産'])}）です。"
    else:
        head += f"負債は資産の{real['負債'] / real['総資産']:.0%}（実質）。"
    return head


def _render_adjustments(fin: Financials, run, session, adj: list) -> None:
    """確かめたい科目の一覧と、実質化の調整の入力・取り消し。入力は論争への介入としても書き込む。"""
    from core import adjust

    st.markdown("##### 実質化で確かめたい科目")
    st.caption("図の中では、これらの科目は帳簿に計上されている区画のまま扱っています。確かめた結果を調整として入力すると、"
               "実質の列と実質の指標に反映され、論争の各担当者も以後その調整を前提に議論します（資金の計算は変わりません）。")
    watch = metrics.watch_items(fin)
    for _key, label, amount, block, why in watch:
        st.markdown(f"- **{label}** {amount:,}千円（{block}）— {why}")
    if not watch:
        st.caption("該当する科目はありません。")
    auto = [a for a in metrics.real_adjustments(fin) if a.origin == "開示"]
    if auto or adj:
        st.markdown("**入っている調整**")
        for a in auto:
            st.markdown(f"- 〔決算書の開示から自動〕{a.describe()}")
        own = {a["id"] for a in run.read(adjust.FILE, [])} if run is not None else set()
        for a in adj:
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"- 〔介入 {a.id}〕{a.describe()}")
            if a.id in own and not run.frozen and c2.button("取り消す", key=f"adj_del_{a.id}", type="tertiary"):
                gone = adjust.remove(run, a.id)
                _tell_debate(session, adjust.intervention_text(gone, removed=True))
                st.rerun()
    if run is None or run.frozen:
        return
    options = [f"{label}（{block}）" for _k, label, _a, block, _w in watch] + ["その他の科目（名前を入力）"]
    with st.form("adj_form", clear_on_submit=True, border=True):
        st.markdown("**調整を入れる（介入）**")
        pick = st.selectbox("科目", options, key="adj_pick")
        other = st.text_input("科目名（その他を選んだとき）", key="adj_name")
        block = st.selectbox("区画（その他を選んだとき）", list(adjust.BLOCKS), key="adj_block")
        amount = st.number_input("増減額（千円。増やすなら＋、減らすなら−）", step=100, value=0, key="adj_amount")
        note = st.text_input("根拠（例：銘柄〇〇の時価、社長への聞き取り）", key="adj_note")
        if st.form_submit_button("調整を入れて論争に伝える", type="primary"):
            if pick.startswith("その他"):
                name, key_, blk = other, None, block
            else:
                w = watch[options.index(pick)]
                name, key_, blk = w[1], w[0], w[3]
            try:
                new = adjust.add(run, name, blk, int(amount), note, key_)
            except ValueError as e:
                st.error(str(e))
            else:
                mid = _tell_debate(session, adjust.intervention_text(new))
                if mid:
                    adjust.set_message_id(run, new.id, mid)
                st.rerun()


def _render_repayment(fin: Financials, run, session) -> None:
    """約定返済額の確定（年間返済額の手動入力）。決算書から約定返済が確かめられないときに、返済予定表を見て入れる。"""
    from core import repayment

    cur = repayment.load(run) if run is not None else None
    doubt = metrics.cash_base(fin).debt_unverified   # 確定の前に、書類だけで確かめられないもの
    if not doubt and cur is None:
        return
    st.markdown("##### 約定返済額の確定（年間返済額の手動入力）")
    if doubt:
        st.caption("決算書から約定返済を確かめられません（" + "・".join(doubt) + "）。資金不足の有無は判定保留です。"
                   "返済予定表（金銭消費貸借契約書）で確かめた年間の約定返済額を入れると、資金の監視をその額で計算し直し、"
                   "判定保留を解除します。決算書の数字は変えません。")
    if cur is not None:
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"- 〔確定済み〕{cur.describe()}　{cur.at}")
        if run is not None and not run.frozen and cur.run_id == run.run_id \
                and c2.button("取り消す", key="repay_del", type="tertiary"):
            gone = repayment.withdraw(run)
            if gone is not None:
                _tell_debate(session, repayment.intervention_text(gone, removed=True))
            st.rerun()
    if run is None or run.frozen:
        return
    with st.form("repay_form", clear_on_submit=True, border=True):
        st.markdown("**約定返済額を確定する（介入）**" if cur is None else "**確定額を入れ直す（介入）**")
        amount = st.number_input("年間約定返済額（千円。長期借入金・社債・リース債務の1年分の合計）", min_value=0,
                                 step=100, value=0, key="repay_amount")
        basis = st.text_input("根拠（例：〇〇銀行・△△信金の返済予定表を確認。毎月元金 834千円）", key="repay_basis")
        if st.form_submit_button("約定返済額を確定して論争に伝える", type="primary"):
            try:
                rec = repayment.confirm(run, int(amount), basis)
            except ValueError as e:
                st.error(str(e))
            else:
                mid = _tell_debate(session, repayment.intervention_text(rec))
                if mid:
                    repayment.set_message_id(run, mid)
                from core.mock_engine import ensure_debt_request

                ensure_debt_request(run)
                st.rerun()


def _tell_debate(session, text: str) -> str | None:
    """調整を論争のタイムラインに介入として書き込み、担当者の文脈を更新する。"""
    if session is None:
        return None
    from core import adjust
    from core.interrupt import intervene

    from core import repayment

    session.ctx.adjustments = adjust.load(session.run)
    if session.ctx.fin is not None:   # 確定した約定返済で資金の基礎値を計算し直す（次の裁定から監視指標に効く）
        session.ctx.base = repayment.cash_base_for(session.run, session.ctx.fin)
    try:
        return intervene(session, text).id
    except Exception:          # 凍結された回次など。調整そのものは保存済み
        return None


def _recon_frame(report: ReconciliationReport) -> pd.DataFrame:
    rows = []
    for c in report.checks:
        row = {"種類": c.group, "検算項目": c.name, "内訳件数": c.n_components}
        for p in c.periods:
            row[f"差（{PERIOD_LABEL[p.period]}）"] = p.diff
            row[f"許容差（{PERIOD_LABEL[p.period]}）"] = p.tolerance
        row["判定"] = c.status
        rows.append(row)
    return pd.DataFrame(rows)


def _render_recon(report: ReconciliationReport, fin: Financials, source_label: str) -> None:
    st.markdown("##### 自動検算ステータス")
    if report.passed and report.count("未確認") == 0:
        st.success(f"全{report.total}項目一致　この数字は論争の根拠に使えます", icon=":material/check_circle:")
    elif report.passed:
        st.warning(f"不一致0件、未確認{report.count('未確認')}件。未確認の項目は論争で使えません", icon=":material/help:")
    else:
        st.error(f"不一致{report.count('不一致')}件。論争に進まず停止します", icon=":material/block:")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("一致", report.count("一致"))
    k2.metric("不一致", report.count("不一致"))
    k3.metric("未確認", report.count("未確認"))
    k4.metric("端数差", report.rounding_diffs,
              help="千円未満切捨ての表示で生じた1〜2千円のずれを、許容差の内として一致とみなした件数（期ごとに数える）")
    if fin.rounding_adjustments:
        total = sum(abs(a.amount) for a in fin.rounding_adjustments)
        st.info(f"診断適格性（DDF）：条件付き適格。人が承認した未解明差異（DM未満）で一致させた項目が{report.adjusted_count}件あります"
                f"（合計{total:,}{fin.unit}）。書類に書かれた合計を正とし、ずれは未解明差異として計上しています", icon=":material/fact_check:")
    rule = "円単位のため許容差0" if fin.rounding == "yen" else "許容差＝内訳件数n千円（最低2千円）"
    st.caption(f"規則：{rule}。{fin.rounding_note}")
    st.caption(f"検算対象：{source_label}（core.guardrails.reconcile の実行結果）")
    with st.expander("この検算は何をしているか", icon=":material/help:"):
        groups = {}
        for c in report.checks:
            groups.setdefault(c.group, []).append(c)
        what = {"BS内訳": "貸借対照表の内訳の合計＝報告された合計（流動資産、固定資産、負債、純資産など）",
                "貸借一致": "資産合計＝負債純資産合計、負債＋純資産＝負債純資産合計",
                "段階利益": "売上総利益→営業利益→経常利益→税引前→当期純利益の積み上げ",
                "原価の流れ": "材料費・労務費・経費→当期製品製造原価→売上原価",
                "指標照合": "本表の数字＝主要な経営指標の欄の数字（売上高・純利益・純資産・総資産）",
                "表間連携": "貸借対照表の仕掛品・製品＝製造原価明細書・売上原価の期末の数字",
                "期首接続": "前期末の数字＝当期首の数字（棚卸資産、繰越利益剰余金、別途積立金）"}
        st.markdown("読み取った数字どうしが、財務諸表の中で辻褄が合っているかを確かめています。"
                    "一つでも不一致があれば、その資料の数字は論争に使いません（根拠がなければ止まる）。")
        import html as _h
        body = "".join(f"<tr><td>{_h.escape(g)}</td><td>{len(cs)}</td><td>{sum(1 for c in cs if c.status == '一致')}</td>"
                       f"<td>{_h.escape(what.get(g, ''))}</td></tr>" for g, cs in groups.items())
        st.html('<div class="dd-cmp-wrap"><table class="dd-cmp dd-basis"><thead><tr><th>種類</th><th>件数</th>'
                f"<th>一致</th><th>確かめていること</th></tr></thead><tbody>{body}</tbody></table></div>")
    with st.expander("検算の明細"):
        df = _recon_frame(report)
        st.dataframe(df, hide_index=True, width="stretch", height=360)
        bad = df[df["判定"] != "一致"]
        if not bad.empty:
            st.markdown("**一致しなかった項目**")
            st.dataframe(bad, hide_index=True, width="stretch")


def _render_requests(requests: list[dict]) -> None:
    st.markdown("##### データ請求（欠落科目アラート）")
    for r in requests:
        color, label = md.REQUEST_BADGE.get(r["status"], ("gray", r["status"]))
        with st.container(border=True):
            must = "　:red-badge[必須]" if r.get("required") else ""
            st.markdown(f"**{r['id']}　{r['item']}**　:{color}-badge[{label}]{must}")
            st.caption(f"担当：Analyst Radar　請求先：{r['request_to']}")
            st.caption(f"解消する争点：{r['resolves']}")
            if r.get("note") and r["status"] != "解消":
                st.caption(r["note"])
            for v in r.get("resolved_by", []) if r["status"] == "解消" else []:
                src = v.get("source") or {}
                where = src.get("file") or ""
                st.caption(f":material/check_circle: 解消：{v['label']} {v['cur']:,}千円（{where}）")
            for rec in r.get("received", []):
                st.caption(f":material/attach_file: {rec['file']}（{rec['run']}）")


def _render_kpis(fin: Financials, mode: str, adj=(), run=None) -> None:
    """全社共通の指標と、条件を満たすときだけの会社固有の指標。各指標に計算式・前期比・出典頁を添える。"""
    from core import repayment

    items = ind.kpis(fin)
    base = metrics.cash_base(fin, repayment.load(run) if run is not None else None)
    rw = metrics.project(base, []).cash_runway_months
    cols = st.columns(4)
    for n, i in enumerate(items):
        v = ind.evaluate(fin, i, mode, adj)
        help_ = f"{i.why}。計算式：{i.formula}\n\n内訳：{v.basis}" + (f"\n\n{v.note}" if v.note else "")
        d = ind.delta_text(v)
        cols[n % 4].metric(i.label, ind.fmt(i, v.cur), d, delta_color="off" if d else "normal", help=help_)
        if n % 4 == 3:
            cols = st.columns(4)
    runway = metrics.runway_label(rw, base.free_cf, short=True, pending=base.shortage_pending)
    cols[len(items) % 4].metric("残余月数（改善前）", runway,
                                help="手元資金 ÷ 返済後の月間流出。\n\n" + "\n\n".join(base.basis))
    st.caption("全社共通：売上高・営業利益率・総資産・自己資本比率・有利子負債・手許現預金・営業利益ROA・残余月数。"
               "会社固有：受取配当金がある会社は受取配当依存、商品仕入がある会社は商品仕入高比率を加えています。"
               "各指標の ? に計算式と出典頁があります")


def render(fin: Financials | None, report: ReconciliationReport | None, mode: str, benchmarks: dict,
           requests: list[dict], source_label: str, run=None, session=None) -> None:
    if fin is None:
        st.info("この回次には財務データがありません。決算書類を投入してください。", icon=":material/info:")
        _render_requests(requests)
        return

    from core import adjust

    adj = adjust.load(run) if run is not None else []
    try:
        bs = metrics.balance_sheet(fin, mode, adj)
    except ValueError as e:
        st.warning(str(e), icon=":material/warning:")
        bs = metrics.balance_sheet(fin, "nominal")
        mode, adj = "nominal", []
    mode_name = "名目BS（帳簿どおり）" if mode == "nominal" else "実質BS（帳簿＋実質化の調整）"
    st.markdown(f"##### 表示モード：{mode_name}")
    st.caption(bs["注記"])

    _render_kpis(fin, mode, adj, run)

    st.divider()
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("##### 比率の突合")
        benches = [b for b in [benchmarks.get("industry")] + benchmarks.get("peers", []) if b][:2]
        if any(b.get("placeholder") for b in benches):
            st.warning(benches[0].get("note", "比較値は仮置きです"), icon=":material/construction:")
        for b in benches:
            if b.get("source"):
                st.markdown(f":material/query_stats: **比較基準：{b['source']}**")
                if b.get("verified") is False and b.get("verification_note"):
                    st.caption(b["verification_note"])
        df = _ratio_frame(fin, mode, benches, adj)
        st.plotly_chart(_ratio_chart(df, benches), width="stretch", theme="streamlit")
        st.markdown("**グラフの基礎数値と典拠**")
        bf = _basis_frame(fin, mode, benches, adj)
        import html as _h
        head = "".join(f"<th>{_h.escape(c)}</th>" for c in bf.columns)
        body = "".join("<tr>" + "".join(f"<td>{_h.escape(str(v))}</td>" for v in r) + "</tr>" for r in bf.itertuples(index=False))
        st.html(f'<div class="dd-cmp-wrap"><table class="dd-cmp dd-basis"><thead><tr>{head}</tr></thead>'
                f"<tbody>{body}</tbody></table></div>")
        st.markdown("##### 貸借対照表（面積が金額に比例）")
        st.plotly_chart(_bs_chart(fin, adj), width="stretch", theme="streamlit")
        st.caption(_bs_caption(fin, adj))
        _render_adjustments(fin, run, session, adj)
        _render_repayment(fin, run, session)
    with right:
        if report is not None:
            _render_recon(report, fin, source_label)
        _render_requests(requests)


GATE_BADGE = {"通過": ("green", "DDF：適格"), "通過（端数調整）": ("green", "DDF：条件付き適格（未解明差異を承認済み）"),
              "軽微": ("orange", "DDF：条件付き適格（承認待ち）"), "差し替え待ち": ("gray", "差し替え待ち（不採用）"),
              "停止": ("red", "DDF：不適格（停止）"), "未確認": ("red", "DDF：不適格（中心の検算を確かめられず停止）"), "対象外": ("gray", "検算対象外（部分資料）")}


def render_extractions(run) -> None:
    """この回次で投入された資料の読み取り結果（tools.file_ingest）を表示する。"""
    import json

    d = run.path / "extracted"
    files = sorted(d.glob("*.json")) if d.exists() else []
    if not files:
        return
    st.divider()
    st.markdown("##### 投入資料の読み取り結果")
    for f in files:
        x = json.loads(f.read_text(encoding="utf-8"))
        with st.container(border=True):
            if x.get("error"):
                st.markdown(f"**{x['file']}**　:red-badge[読み取り失敗]")
                st.caption(x["error"])
                continue
            color, label = GATE_BADGE.get(x["gate"], ("gray", x["gate"]))
            mock = "　:orange-badge[モック]" if x["report"].get("is_mock") else ""
            st.markdown(f"**{x['file']}**　:{color}-badge[{label}]{mock}")
            st.caption(f"{x['summary']}　／　エンジン：{x['extractor']}")
            rep = x["report"]
            details = []
            if rep.get("remapped"):
                details.append("別名の吸収：" + "、".join(rep["remapped"]))
            if rep.get("unverified"):
                details.append("未確認（null）：" + "、".join(rep["unverified"]))
            if rep.get("dropped"):
                details.append("標準科目に当てはまらず除外：" + "、".join(rep["dropped"]))
            if x.get("conflicts_with_existing"):
                details.append("既存の数値との食い違い（上書きせず）：" + "、".join(x["conflicts_with_existing"]))
            for w in rep.get("warnings", []):
                details.append("注意：" + w)
            for line in details:
                st.caption(line)
