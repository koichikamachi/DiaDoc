"""タブ2：財務・4P突合マトリクス。

対象企業の数値は回次の financials.json から、検算は core.guardrails.reconcile の実結果を表示する。
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import mock_data as md
from core import metrics
from schema import Financials, ReconciliationReport

# 既定パレットの先頭3色（隣接・全組合せとも色覚多様性の検証済み）
C_COMPANY = "#2a78d6"
C_AVG = "#eb6834"
C_BENCH = "#1baf7a"

RATIO_ROWS = [
    ("営業利益率", "op_margin", "p.93"),
    ("販管費率", "sga_ratio", "p.93"),
    ("材料費比率（製造費用に占める）", "mat_ratio", "p.94"),
    ("商品仕入高比率（売上高に占める）", "purchase_ratio", "p.94"),
    ("自己資本比率", "equity_ratio", "p.91–92（実質は推計）"),
    ("経常利益に占める受取配当金", "div_dep", "p.93"),
]
PERIOD_LABEL = {"prev": "前期", "cur": "当期"}


def _oku(v: float) -> str:
    return f"{v / 1e5:,.1f}億円"


def _ratio_frame(fin: Financials, mode: str, benches: list[dict]) -> pd.DataFrame:
    comp = metrics.company_ratios(fin, mode)
    rows = []
    for label, key, src in RATIO_ROWS:
        row = {"指標": label, "対象企業": comp[key] * 100}
        for b in benches:
            row[b["name"]] = b["ratios"].get(key, float("nan")) * 100
        row["出典（対象企業）"] = src
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
        st.success(f"全{report.total}項目一致　次工程へ進めます", icon=":material/check_circle:")
    elif report.passed:
        st.warning(f"不一致0件、未確認{report.count('未確認')}件。未確認の項目は論争で使えません", icon=":material/help:")
    else:
        st.error(f"不一致{report.count('不一致')}件。論争に進まず停止します", icon=":material/block:")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("一致", report.count("一致"))
    k2.metric("不一致", report.count("不一致"))
    k3.metric("未確認", report.count("未確認"))
    k4.metric("端数差", report.rounding_diffs, help="許容差内に収まった差の件数（期ごとに数える）")
    rule = "円単位のため許容差0" if fin.rounding == "yen" else "許容差＝内訳件数n千円（最低2千円）"
    st.caption(f"規則：{rule}。{fin.rounding_note}")
    st.caption(f"検算対象：{source_label}（core.guardrails.reconcile の実行結果）")
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

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("売上高", _oku(m["売上高"]), help="有報第73期 p.93（単体）")
    c2.metric("営業利益率", f"{m['営業利益率']:.1%}", help="有報第73期 p.93")
    c3.metric("総資産", _oku(bs["総資産"]), help="名目は有報第73期 p.91、実質は推計")
    c4.metric("自己資本比率", f"{bs['自己資本比率']:.1%}", help="名目は有報第73期 p.91–92、実質は推計")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("商品仕入高", _oku(m["当期商品仕入高"]), f"前期 {m['前期商品仕入高'] / 1e5:,.2f}億円",
              delta_color="off", help="有報第73期 p.94")
    c6.metric("経常利益に占める受取配当金", f"{m['配当依存度']:.0%}", help="有報第73期 p.93")
    c7.metric("営業利益ROA", f"{bs['営業利益ROA']:.1%}", help="営業利益÷総資産")
    c8.metric("有利子負債", _oku(m["有利子負債"]), help="借入金・社債・リース債務 有報第73期 p.92")

    st.divider()
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("##### 比率の突合")
        benches = [b for b in [benchmarks.get("industry")] + benchmarks.get("peers", []) if b][:2]
        if any(b.get("placeholder") for b in benches):
            st.warning(benches[0].get("note", "比較値は仮置きです"), icon=":material/construction:")
        df = _ratio_frame(fin, mode, benches)
        st.plotly_chart(_ratio_chart(df, benches), width="stretch", theme="streamlit")
        with st.expander("表で見る"):
            st.dataframe(df, hide_index=True, width="stretch",
                         column_config={c: st.column_config.NumberColumn(c, format="%.1f%%")
                                        for c in df.columns if c not in ("指標", "出典（対象企業）")})
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
