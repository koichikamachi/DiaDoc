"""Moderator Judge（審判・議長）。中身の審理と論点整理を担う。

形式審査（出典・決着条件・因果ブリッジ・フェーズの規律）とフェーズの判定はプログラムが行う。Judge は
形式審査を通った発言の中身を見て、金額と経路のない抽象論（定性ポエム）を差し戻すことができる。
通過にすることで形式審査の結果を覆すことはできない。
"""

from __future__ import annotations

from agents.base import Agent, ComparisonTurn, JudgeTurn

ROLE = """役割：Moderator Judge（審判・議長）。
- 審査対象として示された発言それぞれについて、中身を審理し reviews に判定を書く。
  - 金額と経路のない抽象論（定性ポエム）、資料と矛盾する数字、因果ブリッジの資金効果に根拠のないもの → 差し戻し
  - 出典の頁に書かれていないことを書かれているかのように言うもの → 退け
  - それ以外 → 通過
- 形式審査で既に差し戻し・退けになった発言は審査対象に含まれない。あなたが通過に戻すことはできない。
- フェーズの判定はプログラムが行う。あなたは判定を変えず、summary で論点を3文以内に整理する。
- 論点の決着・保留があれば agenda_ops（op=close／hold）で示す。"""


class Judge(Agent):
    id = "judge"
    name = "Moderator Judge"

    def role_prompt(self, phase):
        return ROLE

    def review(self, state, ctx, speaker, targets) -> JudgeTurn:
        if not targets:
            return JudgeTurn()
        listing = "\n".join(f"- {m.id}（{m.speaker}／{m.action}）：{m.text}" for m in targets)
        user = self.user_prompt(state, ctx) + "\n\n# 審査対象（形式審査を通過した発言）\n" + listing
        out = speaker.generate(self, self.system_prompt(state.phase, state.mission), user, JudgeTurn, state, ctx)
        return out if isinstance(out, JudgeTurn) else JudgeTurn.model_validate(out)

    def task(self, state, ctx):
        return "審査対象の各発言を審理し、reviews と summary を出してください。"

    def compare(self, state, ctx, speaker, options) -> ComparisonTurn:
        listing = "\n".join(
            f"- {o.name}：残す＝{'・'.join(o.keep)}／捨てる＝{'・'.join(o.discard)}／前提＝{'／'.join(o.preconditions)}"
            for o in options)
        user = self.user_prompt(state, ctx) + "\n\n# 比べる道（Dr. Rebuild の宣告）\n" + listing
        system = f"【診断ミッション】: {state.mission}\n比較はこのミッションに照らして行う。\n\n" + COMPARE
        out = speaker.generate(self, system, user, ComparisonTurn, state, ctx)
        return out if isinstance(out, ComparisonTurn) else ComparisonTurn.model_validate(out)


COMPARE = """役割：Moderator Judge（案件統括・ディレクター）。いまは決着段階（settlement）で、トリアージの道を比べる。
- 宣告された道それぞれを、同じ物差しで評価し assessments に一つずつ書く（道の名前は宣告のとおり、順番も同じ）。
  employment：雇用はどうなるか。cash：当面の資金繰りをどう乗り切るか（何が、いつまでに要るか）。
  creditors：金融機関・債権者に何を求めるか。months_needed：道筋がつくまでの月数の見込み（資料に根拠がなければ保守的に長めに）。
  risks：主なリスクを2〜3件。deciding_fact：この道を選ぶか捨てるかの決め手になる観察事実（例：メインバンクの回答）。
  sources：根拠にした資料と頁（引用できる資料の一覧から）。
- 残余月数と比べて間に合うかどうかはプログラムが判定する。あなたは月数の見込みを正直に書く。
- どの道を選ぶべきかは書かない。選ぶのは経営者と金融機関である。summary には、道を分ける論点だけを3文以内で書く。
- 数字は文脈に示された資料・数字だけを使う。金額は千円。"""
