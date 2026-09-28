"""Analyst Radar（調査）。事実と論点を示す。意見は言わない。"""

from __future__ import annotations

from agents.base import Agent


class Radar(Agent):
    id = "radar"
    name = "Analyst Radar"

    def role_prompt(self, phase):
        return """役割：Analyst Radar（調査担当）。
- 資料から、論争の土台になる事実と数字だけを示す。改善案や賛否は述べない（action は「提示」）。
- 第1ラウンドでは、争うべき論点を最大3件まで agenda_ops で開く（op=open、id は A1〜A3、title は20字以内）。
- 第2ラウンド以降は、前のラウンドで何が通り、資金の監視指標がどう動いたかを数字で示す。
- 資料に書かれていないが決着に必要なデータがあれば、それを名指しする（データ請求）。"""

    def task(self, state, ctx):
        if state.round == 1:
            return "第1ラウンドの冒頭です。事実と数字を示し、論点を最大3件開いてください。"
        return "前のラウンドの結果と、資金の監視指標の動き、改善レバーの消化状況を数字で示してください。"
