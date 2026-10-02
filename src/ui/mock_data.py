"""画面表示用の定数（登場人物と判定バッジ）。

論争の台本・介入規則・資料投入の処理は src/core/mock_engine.py に移した。
数値はすべて data/ 配下の回次フォルダから読み込む。
"""

AGENTS = {
    "rebuild": {"name": "Dr. Rebuild", "role": "再生派", "avatar": ":material/content_cut:", "color": "red"},
    "growth": {"name": "Prof. Growth", "role": "成長派", "avatar": ":material/trending_up:", "color": "green"},
    "radar": {"name": "Analyst Radar", "role": "調査派", "avatar": ":material/radar:", "color": "blue"},
    "judge": {"name": "Moderator Judge", "role": "調停", "avatar": ":material/gavel:", "color": "violet"},
    "human": {"name": "支援担当者", "role": "操作者", "avatar": ":material/person:", "color": "orange"},
}

# 審判の判定（台本上の審理結果）
RULING_BADGE = {
    "通過": ("green", "形式審査通過"),
    "差し戻し": ("orange", "差し戻し"),
    "退け": ("red", "退け"),
    "棄却": ("red", "棄却"),
    "保留": ("gray", "保留"),
    "登録": ("violet", "制約・前提として登録"),
    "再開": ("blue", "審理再開"),
}

# 形式審査（guardrails.review_claim による機械判定）
REVIEW_BADGE = {
    "通過": ("green", "機械判定：通過"),
    "差し戻し": ("orange", "機械判定：差し戻し（決着条件なし）"),
    "退け": ("red", "機械判定：退け（客観的根拠なし）"),
}

REQUEST_BADGE = {
    "請求中": ("orange", ":material/pending: 追加データ請求中"),
    "受領（検証待ち）": ("blue", ":material/inbox: 受領（検証待ち）"),
    "解消": ("green", ":material/check: 解消"),
}
