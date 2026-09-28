"""コックピット画面の見た目（カスタムCSS）。

明暗のテーマは Streamlit の設定に従う（st.context.theme.type）。色の値はここにだけ書き、各部品は役割名
（--dd-ink など）で参照する。
"""

from __future__ import annotations

import streamlit as st

from agents_profile import PROFILES

TOKENS = {
    "light": {"ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781", "hair": "rgba(11,11,11,0.10)",
              "card": "#ffffff", "wash": "#f1efe8", "accent": "#2a78d6", "accent_wash": "rgba(42,120,214,0.10)",
              "ok": "#006300", "back": "#b35c00", "rej": "#d03b3b"},
    "dark": {"ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781", "hair": "rgba(255,255,255,0.12)",
             "card": "#1a1a19", "wash": "#232322", "accent": "#3987e5", "accent_wash": "rgba(57,135,229,0.16)",
             "ok": "#0ca30c", "back": "#fab219", "rej": "#e66767"},
}


def mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # 古い版やテスト環境
        return "light"


def agent_color(agent_id: str) -> str:
    return PROFILES[agent_id][mode()]


def inject() -> None:
    t = TOKENS[mode()]
    m = mode()
    agent_rules = "\n".join(
        f'[class*="st-key-card-{a}-"] {{ border-left: 4px solid {p[m]} !important; }}' for a, p in PROFILES.items())
    st.html(f"""
<style>
:root {{
  --dd-ink: {t['ink']}; --dd-ink2: {t['ink2']}; --dd-muted: {t['muted']}; --dd-hair: {t['hair']};
  --dd-card: {t['card']}; --dd-wash: {t['wash']}; --dd-accent: {t['accent']}; --dd-accent-wash: {t['accent_wash']};
}}
/* 余白を詰めて、画面の縦を論争に使う */
.block-container {{ padding-top: 3.2rem; padding-bottom: 2rem; max-width: 100%; }}

/* ヘッダー */
.dd-header {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:.4rem 1rem; margin-bottom:.2rem; }}
.dd-brand {{ font-size:1.55rem; font-weight:800; color:var(--dd-ink); letter-spacing:.01em; }}
.dd-brand small {{ font-size:.95rem; font-weight:500; color:var(--dd-ink2); margin-left:.4rem; }}
.dd-tagline {{ font-size:.95rem; color:var(--dd-ink2); }}

/* タブ：大きく、太く、選択中をはっきり。
   Streamlit 1.5x までは data-baseweb="tab"、1.6x 以降は data-testid="stTab"（role="tab"）なので両方に当てる */
.stTabs [role="tablist"], .stTabs [data-baseweb="tab-list"] {{ gap:.25rem; border-bottom:1px solid var(--dd-hair); }}
.stTabs [role="tab"], .stTabs [data-baseweb="tab"] {{ height:auto; padding:.6rem 1.15rem; border-radius:8px 8px 0 0; }}
.stTabs [role="tab"] p, .stTabs [data-baseweb="tab"] p {{ font-size:1.1rem !important; font-weight:700 !important;
    color:var(--dd-ink2); }}
.stTabs [role="tab"] p span[role="img"] {{ font-size:1.25rem; }}
.stTabs [role="tab"]:hover, .stTabs [data-baseweb="tab"]:hover {{ background:var(--dd-wash); }}
.stTabs [role="tab"][aria-selected="true"], .stTabs [data-baseweb="tab"][aria-selected="true"] {{
    background:var(--dd-accent-wash); }}
.stTabs [role="tab"][aria-selected="true"] p, .stTabs [data-baseweb="tab"][aria-selected="true"] p {{
    color:var(--dd-accent) !important; }}
.stTabs .react-aria-SelectionIndicator, .stTabs [data-baseweb="tab-highlight"] {{
    background-color:var(--dd-accent) !important; height:3px !important; }}

/* ペインの見出し */
.dd-pane-title {{ font-size:.8rem; font-weight:700; letter-spacing:.08em; color:var(--dd-muted);
                  text-transform:uppercase; margin:.1rem 0 .4rem; }}

/* 発言カード（左の縦線で発言者を示す。色だけに頼らず名前とアイコンも出す） */
[class*="st-key-card-"] {{ background:var(--dd-card); border-radius:10px; }}
{agent_rules}
[class*="st-key-card-human-"] {{ border-left-style: dashed !important; background: var(--dd-wash); }}

/* 発言者の見出し：名前を大きく。色の丸は識別の補助で、名前と肩書が主役 */
.dd-speaker {{ display:flex; flex-wrap:wrap; align-items:center; gap:.2rem .6rem; margin-bottom:.15rem; }}
.dd-av {{ width:1.9rem; height:1.9rem; border-radius:50%; display:inline-flex; align-items:center;
          justify-content:center; color:#fff; font-weight:800; font-size:.95rem; flex:none; }}
.dd-name {{ font-size:1.22rem; font-weight:800; color:var(--dd-ink); letter-spacing:.01em; }}
.dd-role {{ font-size:.86rem; color:var(--dd-ink2); }}
.dd-meta {{ font-size:.8rem; color:var(--dd-muted); }}
.dd-verdict {{ font-size:.8rem; font-weight:700; padding:.08rem .5rem; border-radius:999px; border:1px solid; }}
.dd-ok {{ color:{t['ok']}; border-color:{t['ok']}; }}
.dd-back {{ color:{t['back']}; border-color:{t['back']}; }}
.dd-rej {{ color:{t['rej']}; border-color:{t['rej']}; }}
.dd-muted {{ color:var(--dd-ink2); border-color:var(--dd-hair); }}

/* ラウンドの区切り */
.dd-round {{ display:flex; align-items:center; gap:.6rem; margin:.5rem 0 .1rem; color:var(--dd-muted);
             font-size:.8rem; font-weight:700; letter-spacing:.05em; }}
.dd-round::before, .dd-round::after {{ content:""; flex:1; border-top:1px solid var(--dd-hair); }}

/* Judge の裁定 */
.dd-tally {{ display:flex; flex-wrap:wrap; gap:.4rem; margin:.2rem 0 .4rem; }}
.dd-mini {{ display:flex; flex-wrap:wrap; gap:.3rem 1.1rem; font-size:.8rem; color:var(--dd-ink2);
            padding:.4rem .6rem; border-radius:8px; background:var(--dd-wash); }}
.dd-mini b {{ display:block; font-size:1rem; color:var(--dd-ink); font-variant-numeric:tabular-nums; }}
.dd-phase {{ margin:.4rem 0; padding:.55rem .75rem; border-radius:8px; border:1px solid var(--dd-hair);
             border-left:4px solid var(--dd-accent); background:var(--dd-accent-wash); color:var(--dd-ink); font-size:.92rem; }}
.dd-phase-triage_ready {{ border-left-color:{t['rej']}; }}

/* 採否ステータスと KPI の「議論中」印 */
.dd-prop {{ padding:.45rem 0; border-top:1px solid var(--dd-hair); font-size:.88rem; color:var(--dd-ink); }}
.dd-prop:first-child {{ border-top:none; }}
.dd-prop-title {{ font-weight:700; margin:.2rem 0 .05rem; white-space:normal; overflow-wrap:anywhere; line-height:1.4; }}
.dd-more {{ margin-top:.2rem; font-size:.8rem; color:var(--dd-ink2); }}
.dd-more summary {{ cursor:pointer; color:var(--dd-accent); font-weight:700; }}
.dd-more div {{ margin-top:.25rem; line-height:1.5; color:var(--dd-ink); }}
.dd-sub {{ font-size:.78rem; color:var(--dd-ink2); font-variant-numeric:tabular-nums; }}
.dd-live {{ margin-left:.35rem; font-size:.66rem; font-weight:700; color:var(--dd-accent);
            border:1px solid var(--dd-accent); border-radius:999px; padding:0 .3rem; }}

/* ボトルネック */
.dd-bn {{ list-style:none; margin:0 !important; padding:0 !important; display:flex; flex-direction:column; gap:.35rem; }}
.dd-bn li {{ font-size:.85rem; color:var(--dd-ink); line-height:1.4; }}
.dd-bn .dd-tag {{ min-width:2.4rem; }}

/* 診断ミッション */
.dd-mission {{ border:1px solid var(--dd-accent); border-left:4px solid var(--dd-accent); border-radius:10px;
               padding:.5rem .7rem; background:var(--dd-accent-wash); margin-bottom:.4rem; }}
.dd-mission-k {{ font-size:.72rem; font-weight:800; letter-spacing:.06em; color:var(--dd-accent); }}
.dd-mission-v {{ font-size:.95rem; font-weight:700; color:var(--dd-ink); line-height:1.4; }}

/* 資料ドック：資料名のボタンを左寄せ・太字に */
.st-key-dock-docs [data-testid="stBaseButton-tertiary"] {{ justify-content:flex-start; text-align:left; padding:0;
    min-height:1.6rem; font-weight:700; color:var(--dd-ink); }}
.st-key-dock-docs [data-testid="stBaseButton-tertiary"] p {{ font-weight:700; text-align:left; }}
.st-key-dock-docs [data-testid="stCaptionContainer"] {{ margin-top:-.5rem; margin-bottom:.2rem; }}

/* 資料ドック */
.dd-docs {{ list-style:none; margin:0 !important; padding:0 !important; display:flex; flex-direction:column; gap:.45rem; }}
.dd-docs li {{ font-size:.88rem; color:var(--dd-ink); line-height:1.35; }}
.dd-doc {{ font-weight:700; }}
.dd-origin {{ font-size:.74rem; color:var(--dd-muted); }}
.dd-tag {{ display:inline-block; min-width:2.2rem; text-align:center; font-size:.7rem; font-weight:700;
           padding:.05rem .3rem; margin-right:.4rem; border-radius:4px; border:1px solid; }}
.dd-tag-fin {{ color:{t['accent']}; border-color:{t['accent']}; }}
.dd-tag-qual {{ color:{t['ok']}; border-color:{t['ok']}; }}
.dd-tag-calc, .dd-tag-misc {{ color:var(--dd-ink2); border-color:var(--dd-hair); }}
.dd-new {{ font-size:.7rem; font-weight:700; color:{t['back']}; margin-left:.4rem; }}

/* 選択肢の比較表 */
.dd-cmp-wrap {{ overflow-x:auto; margin:.3rem 0 .5rem; }}
.dd-cmp {{ border-collapse:collapse; width:100%; table-layout:fixed; font-size:.78rem; color:var(--dd-ink); }}
.dd-cmp th:first-child {{ width:6.2em; }}
.dd-cmp th, .dd-cmp td {{ border:1px solid var(--dd-hair); padding:.35rem .45rem; vertical-align:top; text-align:left; }}
.dd-cmp thead th {{ background:var(--dd-wash); font-weight:800; }}
.dd-cmp tbody th {{ color:var(--dd-ink2); font-weight:700; background:var(--dd-wash); }}

/* トリアージの選択肢 */
.dd-options {{ display:flex; flex-direction:column; gap:.4rem; margin:.4rem 0; }}
.dd-option {{ border:1px solid var(--dd-hair); border-radius:8px; padding:.45rem .7rem; font-size:.88rem;
              color:var(--dd-ink); background:var(--dd-card); }}
.dd-option-name {{ font-weight:800; margin-bottom:.15rem; }}
.dd-pre {{ margin:.1rem 0 0 1.1rem; padding:0; font-size:.84rem; }}
.dd-k {{ display:inline-block; min-width:3.2rem; font-size:.75rem; color:var(--dd-ink2); }}

/* 因果ブリッジの帯 */
.dd-bridge {{ display:flex; flex-wrap:wrap; gap:.35rem .8rem; align-items:center; padding:.35rem .6rem;
              margin:.3rem 0; border:1px solid var(--dd-hair); border-radius:8px; background:var(--dd-wash);
              font-size:.86rem; color:var(--dd-ink); }}
.dd-bridge b {{ font-variant-numeric: tabular-nums; }}
.dd-bridge .dd-late {{ color:var(--dd-ink2); text-decoration: line-through; }}
.dd-bridge .dd-when {{ font-weight:700; }}

/* KPIカード */
.dd-kpi {{ border:1px solid var(--dd-hair); border-radius:10px; padding:.55rem .7rem; background:var(--dd-card); }}
.dd-kpi .k {{ font-size:.78rem; color:var(--dd-ink2); }}
.dd-kpi .v {{ font-size:1.35rem; font-weight:700; color:var(--dd-ink); line-height:1.25; }}
.dd-kpi .s {{ font-size:.72rem; color:var(--dd-muted); }}

/* 狭い画面：3ペインを縦に積み、対話タイムラインを先頭に出す */
@media (max-width: 1100px) {{
  .st-key-cockpit [data-testid="stHorizontalBlock"]:has(.st-key-pane-center) {{ flex-wrap: wrap; }}
  [data-testid="stColumn"]:has(.st-key-pane-left), [data-testid="stColumn"]:has(.st-key-pane-center),
  [data-testid="stColumn"]:has(.st-key-pane-right) {{ flex: 1 1 100% !important; min-width: 100% !important; }}
  [data-testid="stColumn"]:has(.st-key-pane-center) {{ order: -1; }}
}}
@media (max-width: 700px) {{
  .block-container {{ padding-left: .8rem; padding-right: .8rem; }}
  .stTabs [role="tab"] p, .stTabs [data-baseweb="tab"] p {{ font-size:1rem !important; }}
}}
</style>
""")
