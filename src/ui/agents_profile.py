"""画面に出す「同じ案件を担当する同僚コンサルタントチーム」の表記と色。

色は識別の補助にとどめ、必ずアイコンと名前・肩書を添える（色だけで意味を運ばない）。
論争の当事者3人だけに色（検証済みの分類色の先頭3色）を割り当て、ディレクターと人間は無彩色で区別する。
"""

from __future__ import annotations

# light / dark の値は dataviz 参照パレットの slot1〜3（全組み合わせで色覚多様性の検証済み）
PROFILES = {
    "radar": {"name": "Analyst Radar", "title": "データ解析・客観調査", "duty": "リサーチ担当",
              "icon": ":material/radar:", "glyph": "◎", "light": "#2a78d6", "dark": "#3987e5"},
    "rebuild": {"name": "Dr. Rebuild", "title": "事業再生・財務規律", "duty": "外科手術担当",
                "icon": ":material/healing:", "glyph": "✚", "light": "#eb6834", "dark": "#d95926"},
    "growth": {"name": "Prof. Growth", "title": "現場改善・事業成長", "duty": "オペレーション担当",
               "icon": ":material/trending_up:", "glyph": "▲", "light": "#1baf7a", "dark": "#199e70"},
    "judge": {"name": "Moderator Judge", "title": "案件統括・進行裁定", "duty": "ディレクター",
              "icon": ":material/gavel:", "glyph": "§", "light": "#52514e", "dark": "#c3c2b7"},
    "human": {"name": "支援担当者", "title": "支援担当者介入", "duty": "操作者",
              "icon": ":material/person:", "glyph": "●", "light": "#52514e", "dark": "#c3c2b7"},
}
TEAM = ("rebuild", "growth", "radar", "judge")

# 判定（状態色は固定。アイコンとラベルを必ず添える）
VERDICT = {
    "通過": {"icon": ":material/check_circle:", "color": "green", "label": "通過"},
    "差し戻し": {"icon": ":material/undo:", "color": "orange", "label": "差し戻し"},
    "退け": {"icon": ":material/block:", "color": "red", "label": "退け"},
}

PHASE = {
    "exploration": {"label": "探索", "icon": ":material/explore:", "color": "blue"},
    "triage_ready": {"label": "トリアージ", "icon": ":material/emergency:", "color": "red"},
    "settlement": {"label": "決着", "icon": ":material/flag:", "color": "gray"},
}


def label(agent_id: str) -> str:
    p = PROFILES[agent_id]
    return f"{p['name']}｜{p['title']}（{p['duty']}）"
