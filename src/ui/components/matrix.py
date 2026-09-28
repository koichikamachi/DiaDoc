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


def _ratio_frame(fin: Financials, mode: str, benches: list[dict]) -> pd.DataFrame:
    rows = []
    for i in ind.RATIOS:
        v = ind.evaluate(fin, i, mode)
        row = {"指標": i.label, "対象企業": None if v.cur is None else v.cur * 100}
        for b in benches:
            row[b["name"]] = b["ratios"].get(i.key, float("nan")) * 100
        rows.append(row)
    return pd.DataFrame(rows)


def _basis_frame(fin: Financials, mode: str, benches: list[dict]) -> pd.DataFrame:
    """グラフの基礎数値：比率ごとに計算式、分子・分母の内訳（科目・金額・出典頁）、比較値とその出典。"""
    rows = []
    for i in ind.RATIOS:
        v = ind.evaluate(fin, i, mode)
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


def _bs_chart(fin: Financials) -> go.Figure:
    nom, real = metrics.balance_sheet(fin, "nominal"), metrics.balance_sheet(fin, "real")
    labels = ["名目BS", "実質本業BS"]
    fig = go.Figure()
    fig.add_bar(y=labels, x=[nom["事業資産"] / 1e5, real["事業資産"] / 1e5], name="事業資産", orientation="h",
                marker_color=C_COMPANY, hovertemplate="%{y}<br>事業資産：%{x:,.1f}億円<extra></extra>")
    fig.add_bar(y=labels, x=[nom["投資有価証券"] / 1e5, real["投資有価証券"] / 1e5], name="投資有価証券", orientation="h",
                marker_color=C_AVG, hovertemplate="%{y}<br>投資有価証券：%{x:,.1f}億円<extra></extra>")
    fig.update_layout(
        barmode="stack", height=200, margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, traceorder="normal"),
        xaxis=dict(ticksuffix="億円", showgrid=True), yaxis=dict(autorange="reversed"),
    )
    return fig


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
            st.markdown(f"**{r['id']}　{r['item']}**　:{color}-badge[{label}]")
            st.caption(f"担当：Analyst Radar　請求先：{r['request_to']}")
            st.caption(f"解消する争点：{r['resolves']}")
            for rec in r.get("received", []):
                st.caption(f":material/attach_file: {rec['file']}（{rec['run']}）")


def _render_kpis(fin: Financials, mode: str) -> None:
    """全社共通の指標と、条件を満たすときだけの会社固有の指標。各指標に計算式・前期比・出典頁を添える。"""
    items = ind.kpis(fin)
    base = metrics.cash_base(fin)
    rw = metrics.project(base, []).cash_runway_months
    cols = st.columns(4)
    for n, i in enumerate(items):
        v = ind.evaluate(fin, i, mode)
        help_ = f"{i.why}。計算式：{i.formula}\n\n内訳：{v.basis}" + (f"\n\n{v.note}" if v.note else "")
        d = ind.delta_text(v)
        cols[n % 4].metric(i.label, ind.fmt(i, v.cur), d, delta_color="off" if d else "normal", help=help_)
        if n % 4 == 3:
            cols = st.columns(4)
    runway = "資金流出なし" if rw is None else f"{rw:.1f}か月"
    cols[len(items) % 4].metric("残余月数（改善前）", runway,
                                help="手元資金 ÷ 返済後の月間流出。\n\n" + "\n\n".join(base.basis))
    st.caption("全社共通：売上高・営業利益率・総資産・自己資本比率・有利子負債・手許現預金・営業利益ROA・残余月数。"
               "会社固有：受取配当金がある会社は受取配当依存、商品仕入がある会社は商品仕入高比率を加えています。"
               "各指標の ? に計算式と出典頁があります")


def render(fin: Financials | None, report: ReconciliationReport | None, mode: str, benchmarks: dict,
           requests: list[dict], source_label: str) -> None:
    if fin is None:
        st.info("この回次には財務データがありません。決算書類を投入してください。", icon=":material/info:")
        _render_requests(requests)
        return

    bs = metrics.balance_sheet(fin, mode)
    m = metrics.core_metrics(fin)
    mode_name = "名目BS（制度会計・時価評価）" if mode == "nominal" else "実質本業BS（株式含み益控除・中小企業基準）"
    st.markdown(f"##### 表示モード：{mode_name}")
    st.caption(bs["注記"])

    _render_kpis(fin, mode)

    st.divider()
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("##### 比率の突合")
        benches = [b for b in [benchmarks.get("industry")] + benchmarks.get("peers", []) if b][:2]
        if any(b.get("placeholder") for b in benches):
            st.warning(benches[0].get("note", "比較値は仮置きです"), icon=":material/construction:")
        df = _ratio_frame(fin, mode, benches)
        st.plotly_chart(_ratio_chart(df, benches), width="stretch", theme="streamlit")
        st.markdown("**グラフの基礎数値と典拠**")
        bf = _basis_frame(fin, mode, benches)
        import html as _h
        head = "".join(f"<th>{_h.escape(c)}</th>" for c in bf.columns)
        body = "".join("<tr>" + "".join(f"<td>{_h.escape(str(v))}</td>" for v in r) + "</tr>" for r in bf.itertuples(index=False))
        st.html(f'<div class="dd-cmp-wrap"><table class="dd-cmp dd-basis"><thead><tr>{head}</tr></thead>'
                f"<tbody>{body}</tbody></table></div>")
        st.markdown("##### 名目と実質の資産構成")
        st.plotly_chart(_bs_chart(fin), width="stretch", theme="streamlit")
        nom, real = metrics.balance_sheet(fin, "nominal"), metrics.balance_sheet(fin, "real")
        share = 1 - real["総資産"] / nom["総資産"]
        st.caption(f"名目の総資産のうち約{share:.0%}が株式の含み益。含み益を除くと、本業の総資産は約{real['総資産'] / 1e5:,.0f}億円になる（推計）。")
    with right:
        if report is not None:
            _render_recon(report, fin, source_label)
        _render_requests(requests)


GATE_BADGE = {"通過": ("green", "検算ゲート通過"), "停止": ("red", "検算ゲートで停止"), "対象外": ("gray", "検算対象外（部分資料）")}


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
