"""右ペイン：ライブ・メトリクス（KPI）、ボトルネックと因果関係、採否ステータス。

数字は財務データ（出典頁付き）と監視指標から、要約は core.digest から決定論的に出す。
"""

from __future__ import annotations

import html

import streamlit as st

from agents_profile import PROFILES
from core import digest, metrics
from schema import Financials
from state import DebateState

STATUS = {
    "審査通過・時期内": ("ok", "✓"), "一部のみ間に合う": ("back", "◐"), "審査通過・時期外": ("muted", "…"),
    "減額採択": ("back", "▽"), "棄却": ("rej", "✕"), "審理中": ("muted", "○"),
}
KPI_ACCOUNTS = {"売上高": {"sales"}, "営業利益率": {"sales", "lab", "mat", "exp"}, "手許現預金": {"cash"},
                "借入残高": {"stl", "cltd", "ltd", "cls", "lls", "bond", "cbond"}}


def _kpi(col, k: str, v: str, s: str, live: bool = False) -> None:
    tag = '<span class="dd-live">議論中</span>' if live else ""
    col.markdown(f'<div class="dd-kpi"><div class="k">{k}{tag}</div><div class="v">{v}</div><div class="s">{s}</div></div>',
                 unsafe_allow_html=True)


def _oku(v: int) -> str:
    return f"{v / 100_000:,.1f}億円"


def _kpis(fin: Financials, state: DebateState | None, base, adjustments=()) -> None:
    m = metrics.core_metrics(fin)
    try:
        roa_s = f"{metrics.balance_sheet(fin, 'real', adjustments)['営業利益ROA'] * 100:.1f}%"
    except ValueError:
        roa_s = "—"
    mon = state.monitor if state else metrics.project(base, [])
    rw = metrics.runway_label(mon.cash_runway_months, metrics.net_after_improvement(mon), short=True)
    if mon.base_runway_months is not None and mon.cash_runway_months != mon.base_runway_months:
        rw_sub = f"改善前 {mon.base_runway_months:.1f}か月 → 通過した改善を反映"
    else:
        rw_sub = "手元資金÷返済後の月間流出"
    touched = digest.mentioned_accounts(state)
    rows = [
        ("売上高", _oku(m["売上高"]), fin.fiscal_period.split("（")[0]),
        ("営業利益率", f"{m['営業利益率'] * 100:.1f}%", "営業利益÷売上高"),
        ("実質ROA", roa_s, "営業利益÷実質の総資産"),
        ("手許現預金", _oku(m["現金預金"]), "期末残高"),
        ("借入残高", _oku(m["有利子負債"]), "短期・長期・社債・リース"),
        ("残余月数", rw, rw_sub),
    ]
    for i in range(0, 6, 2):
        a, b = st.columns(2)
        for col, (k, v, s) in ((a, rows[i]), (b, rows[i + 1])):
            _kpi(col, k, v, s, live=bool(KPI_ACCOUNTS.get(k, set()) & touched) or (k == "残余月数" and mon.counted))
        st.write("")


def _clip(t: str, n: int = 70) -> str:
    return t if len(t) <= n else t[:n] + "…"


def _bottlenecks(state: DebateState | None, base) -> None:
    with st.container(border=True):
        st.markdown("**ボトルネックと因果関係**")
        items = digest.bottlenecks(state, base)
        cls = {"資金": "fin", "時期": "calc", "根拠": "misc", "前提": "qual"}
        st.html('<ul class="dd-bn">' + "".join(
            f'<li><span class="dd-tag dd-tag-{cls[b.kind]}">{b.kind}</span>{html.escape(_clip(b.text))}</li>'
            for b in items) + "</ul>")


def _statuses(state: DebateState | None) -> None:
    with st.container(border=True):
        st.markdown("**採否ステータス**")
        props = digest.proposals(state)
        st.caption("審査と資金の時間軸で見た扱いです。採用するかどうかは、人間が「採択の記録」（意思決定ツリーのタブ）で決めます")
        if not props:
            st.caption("まだ改善案は出ていません")
        rows = []
        for p in props:
            cls, mark = STATUS[p.status]
            who = PROFILES[p.speaker]["name"]
            sub = "".join(
                f'<div class="dd-sub">{"✓" if b.in_time else ("✕" if b.in_time is False else "・")} {html.escape(b.label)}'
                f'{b.direction} 資金{b.cf_effect:+,}{"／年" if b.recurring else "（一回）"}・{b.lead_months}か月後</div>'
                for b in p.bridges)
            body = html.escape(p.body).replace("\n", "<br>")
            rows.append(f'<div class="dd-prop"><span class="dd-verdict dd-{cls}">{mark} {p.status}</span>'
                        f'<div class="dd-prop-title">{html.escape(p.title)}</div>'
                        f'<div class="dd-origin" style="margin-left:0">{who}・第{p.round}ラウンド・{html.escape(p.reason)}</div>'
                        f'{sub}<details class="dd-more"><summary>本文を読む</summary><div>{body}</div></details></div>')
        if rows:
            st.html("".join(rows))
        tri = digest.triage(state)
        if tri:
            cmp_ = digest.comparison(state)
            by_name = {a.name: a for a in cmp_.comparison} if cmp_ else {}
            st.markdown("**Level 0 の道**　:gray[人間が選ぶ]")
            rows = []
            for o in tri.options:
                a = by_name.get(o.name)
                if a and a.months_needed is not None:
                    ok = a.in_time
                    tag = (f'<span class="dd-verdict dd-{"ok" if ok else "rej"}">{"✓" if ok else "✕"} '
                           f'{a.months_needed}か月で道筋</span>') if ok is not None else f"{a.months_needed}か月"
                    fact = f'<div class="dd-sub">決め手：{html.escape(a.deciding_fact)}</div>'
                else:
                    tag, fact = '<span class="dd-verdict dd-muted">◇ 比較前</span>', ""
                rows.append(f'<div class="dd-prop">{tag}<div class="dd-prop-title">{html.escape(o.name)}</div>'
                            f'<div class="dd-origin">前提 {len(o.preconditions)}件：'
                            f'{html.escape(o.preconditions[0] if o.preconditions else "—")}</div>{fact}</div>')
            st.html("".join(rows))
            if cmp_:
                st.caption("比べた表は、対話タイムラインの最後と「意思決定ツリー」タブ（全幅）にあります")


def render(fin: Financials | None, state: DebateState | None, base, adjustments=()) -> None:
    st.markdown('<div class="dd-pane-title">ライブ・メトリクス</div>', unsafe_allow_html=True)
    if fin is None:
        st.info("財務データがありません")
        return
    _kpis(fin, state, base, adjustments)
    _bottlenecks(state, base)
    _statuses(state)
