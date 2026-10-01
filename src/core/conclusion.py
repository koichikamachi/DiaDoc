"""診断の結論：進行状況の表示、決着時のサマリーバナー、診断レポート（Markdown）。すべて決定論（LLM は使わない）。

用語をそろえる。
- 分析回次（第N次分析）：資料の束ごとの分析のまとまり。決算書を差し替えると次の回次になる
- ラウンド：一つの回次の中での対話の順番（Radar→Growth→Rebuild→Judge で1ラウンド）

回次の状態は、ラウンドの進み具合と論争の結末から一つだけ決める（「作業中」と「決着」を並べない）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

# 論争の止まった理由 → 結末の分類
SUFFICIENT = "充足決着"
NEEDS_MORE = "要追加検討"
TRIAGE = "トリアージ宣告"
NO_SHORTAGE = "資金不足なし"

_OUTCOME = {
    "改善策で充足": SUFFICIENT,
    "トリアージ宣告": TRIAGE,
    "膠着（資金不足なし）": NO_SHORTAGE,
}


@dataclass
class Outcome:
    kind: str            # 充足決着／要追加検討／トリアージ宣告／資金不足なし
    stop_reason: str     # 論争が止まった理由（プログラムの判定のまま）

    @property
    def label(self) -> str:
        return f"診断完了・{self.kind}"

    @property
    def tone(self) -> str:   # 画面の枠色
        return {SUFFICIENT: "success", NO_SHORTAGE: "info", TRIAGE: "error"}.get(self.kind, "warning")


def finished(state) -> bool:
    return state is not None and state.phase == "settlement" and state.next_speaker is None


def outcome(state, base=None) -> Outcome | None:
    """論争の結末。終わっていなければ None。

    上限到達で閉じても、資金の不足がない（しかも判定保留でない）会社は「資金不足なし」とする。
    """
    if not finished(state):
        return None
    reason = state.stop_reason or "—"
    kind = _OUTCOME.get(reason)
    if kind is None and reason == "上限到達":
        b = base if base is not None else state.monitor.base
        if b.required_cf == 0 and not b.shortage_pending:
            kind = NO_SHORTAGE
    return Outcome(kind=kind or NEEDS_MORE, stop_reason=reason)


def status_label(run, state, base=None) -> str:
    """ヘッダーとサイドバーに出す回次の状態（一つだけ）。"""
    if state is None or not state.messages:
        head = "未開始"
    else:
        o = outcome(state, base)
        head = o.label if o else f"進行中：第{state.round}ラウンド"
    return f"凍結・閲覧のみ／{head}" if run.frozen else head


def run_heading(run, state, base=None) -> str:
    """例：第1次分析（進行中：第2ラウンド）／第1次分析（診断完了・充足決着）"""
    return f"{run.meta.label}（{status_label(run, state, base)}）"


# ---------------------------------------------------------------------------
# 決着時のサマリーバナー
# ---------------------------------------------------------------------------
@dataclass
class Banner:
    tone: str
    icon: str
    title: str
    lines: list[str] = field(default_factory=list)


def live_monitor(state, base):
    """資金の基礎値が論争中と変わっていれば（約定返済の確定など）、通過した改善で監視指標を計算し直す。"""
    from core.metrics import project

    m = state.monitor
    if base is None or m.base.model_dump() == base.model_dump():
        return m
    mon = project(base, state.passed_bridges(), m.stalemate_count, m.rounds_completed)
    return mon.model_copy(update={"levers_tried": m.levers_tried})


def _counted_measures(state) -> tuple[list[tuple[str, int, int]], list[tuple[str, int]]]:
    """数えた施策：継続改善CF（見出し、年額、効き始める月）と一括調達（見出し、額）。資金効果の大きい順。"""
    from core.digest import proposals

    run_: list[tuple[str, int, int]] = []
    shot: list[tuple[str, int]] = []
    for p in proposals(state):
        if p.status not in ("審査通過・時期内", "一部のみ間に合う", "減額採択"):
            continue
        rec = [b for b in p.bridges if b.in_time and b.recurring and b.cf_effect > 0]
        one = [b for b in p.bridges if b.in_time and not b.recurring and b.cf_effect > 0]
        if rec:
            run_.append((p.title, sum(b.cf_effect for b in rec), min(b.lead_months for b in rec)))
        if one:
            shot.append((p.title, sum(b.cf_effect for b in one)))
    return sorted(run_, key=lambda x: -x[1]), sorted(shot, key=lambda x: -x[1])


def _repay_line(base) -> str:
    from core.metrics import debt_doubt_text

    if base.debt_confirmed:
        return base.debt_confirmed.replace("約定返済＝", "確定した約定返済：年", 1)
    if base.debt_unverified:
        return debt_doubt_text(base)
    return f"約定返済：年{base.debt_service:,}千円（決算書どおり）" if base.debt_service is not None else ""


def banner(state, base, requests: list[dict] | None = None) -> Banner | None:
    """論争が終わったときに画面の上に出す結論のカード。終わっていなければ None。"""
    from core.guardrails import LEVERS
    from core.metrics import reference_text, tri

    o = outcome(state, base)
    if o is None:
        return None
    m = live_monitor(state, base)
    b = m.base
    runs, shots = _counted_measures(state)
    measures = "、".join(f"{t}（年{v:,}千円・{lead}か月後から）" for t, v, lead in runs[:3])
    shot_total = sum(v for _, v in shots)
    lines: list[str] = []
    if (rp := _repay_line(b)):
        lines.append(rp)
    if o.kind == SUFFICIENT:
        title = f"診断完了：必要CF（年間 {b.required_cf:,}千円）の確保シナリオが策定されました"
        lines.append(f"主たる施策：{measures or '—'}。継続改善CF 年{m.accumulated_recovery_cf:,}千円"
                     f"（必要CF 年{b.required_cf:,}千円に対して）")
        icon = ":material/sports_score:"
    elif o.kind == NO_SHORTAGE:
        title = "診断完了：資金不足は示されていません（争点は資金以外）"
        lines.append(f"返済後の資金収支は年{tri(b.free_cf)}千円。通過した継続改善CF 年{m.accumulated_recovery_cf:,}千円"
                     + (f"（{measures}）" if measures else ""))
        icon = ":material/task_alt:"
    elif o.kind == TRIAGE:
        from core.digest import triage

        t = triage(state)
        ways = "／".join(x.name for x in t.options) if t else "—"
        title = "診断完了：改善策だけでは必要CFに届かず、トリアージを宣告しました（道を選ぶのは人間です）"
        lines.append(f"必要CF 年{b.required_cf:,}千円に対し、継続改善CFは年{m.accumulated_recovery_cf:,}千円"
                     f"（不足 年{(m.gap or 0):,}千円）。宣告された道：{ways}")
        if state.adopted_option:
            lines.append(f"採択の記録：{state.adopted_option}" + (f"（{state.adopted_note}）" if state.adopted_note else ""))
        icon = ":material/emergency:"
    else:
        title = f"診断完了（要追加検討）：{o.stop_reason}"
        if b.shortage_pending:
            lines.append(f"資金不足の有無は判定保留。{reference_text(b)}")
        elif b.required_cf:
            lines.append(f"必要CF 年{b.required_cf:,}千円に対し、継続改善CFは年{m.accumulated_recovery_cf:,}千円"
                         f"（残りの不足 年{(m.gap or 0):,}千円）" + (f"。数えた施策：{measures}" if measures else ""))
        untried = [lv for lv in LEVERS if lv not in m.levers_tried]
        if untried:
            lines.append("未着手のレバー：" + "／".join(untried))
        icon = ":material/manage_search:"
    if shot_total:
        lines.append(f"一括調達（一時的資金）：{shot_total:,}千円（" + "、".join(t for t, _ in shots[:2]) + "）")
    open_req = [r for r in requests or [] if r.get("status") != "解消"]
    if open_req:
        must = sum(1 for r in open_req if r.get("required"))
        lines.append(f"未解決の宿題：{len(open_req)}件" + (f"（うち必須{must}件）" if must else ""))
    return Banner(tone=o.tone, icon=icon, title=title, lines=lines)


# ---------------------------------------------------------------------------
# 診断レポート（Markdown）
# ---------------------------------------------------------------------------
def _company_name(run) -> str:
    from core.runs import company_dir

    try:
        meta = json.loads((company_dir(run.company) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return run.company
    return meta.get("display_name") or run.company


def _clip(t: str, n: int = 120) -> str:
    t = " ".join((t or "").split())
    return t if len(t) <= n else t[:n] + "…"


def _attacks(state) -> list[str]:
    """Dr. Rebuild の反論（攻撃）と、その扱い。"""
    from core.challenge import effective_attacks

    latest_review: dict[str, object] = {}
    for r in state.rulings:
        if r.by == "review":
            latest_review[r.message_id] = r
    live = {a.id for atts in effective_attacks(state.messages, state.rulings).values() for a in atts}
    out = []
    for m in state.messages:
        if m.speaker != "rebuild" or m.action != "攻撃":
            continue
        r = latest_review.get(m.id)
        if r is None:
            how = "審査前"
        elif r.verdict != "通過":
            how = f"審査で{r.verdict}（{_clip(r.reasons[0] if r.reasons else '', 60)}）"
        elif m.id in live:
            how = "効いている（提案の減額採択・差し戻しの根拠）"
        elif m.target_message:
            how = "防御で打ち消された、または反論の額が提案を下回らない"
        else:
            how = "審査は通過（特定の提案を名指ししていないため、数えた額は変えていない）"
        target = f"→ {m.target_message}" if m.target_message else ""
        cf = "" if m.feasible_cf is None else f"・現実的な資金効果 {m.feasible_cf:,}千円"
        out.append(f"- {m.id}{target}{cf}：{_clip(m.text)}　【{how}】")
    return out


def _meta(run) -> dict:
    from core.runs import company_dir

    try:
        return json.loads((company_dir(run.company) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _plain_name(run) -> str:
    """文章の中で呼ぶ会社名（ID や「架空モデル」の注記を付けない名前）。"""
    return _meta(run).get("name") or run.company


def abstract(run, fin, state, base, o, requests: list[dict]) -> list[str]:
    """要約（新聞のリード、論文のアブストラクトに当たる）。本文を読まなくても、何の診断で、結論は何で、
    なぜそうなり、次に何が要るかが分かるように、プログラムが数字から組み立てる。"""
    from core.digest import triage
    from core.metrics import tri

    name = _plain_name(run)
    period = f"{fin.fiscal_period}の決算書" if fin is not None and fin.fiscal_period else "決算書"
    from state import DEFAULT_MISSION

    ms = state.mission if state is not None and state.mission else (_meta(run).get("mission") or DEFAULT_MISSION)
    mission = f"「{ms}」を目的として"
    S = [f"本レポートは、{name}の{period}をもとに、{mission}行った{run.meta.label}の結果である。"]
    if fin is None or base is None:
        S.append("財務データがまだないため、資金の診断はできていない。財務書類の投入が必要である。")
        return ["".join(S), ""]
    started = state is not None and bool(state.messages)
    if o is not None:
        S.append(f"結論は「{o.kind}」である。")
    elif started:
        S.append(f"論争は第{state.round}ラウンドの途中であり、結論はまだ出ていない（途中経過）。")
    else:
        S.append("論争はまだ始まっておらず、結論は出ていない。")

    m = live_monitor(state, base) if state is not None else None
    acc = m.accumulated_recovery_cf if m else 0
    gap = m.gap if m else None
    if base.shortage_pending:
        ref = (f"（仮に10年均等返済とすると、返済後の資金収支は年{tri(base.ref_free_cf)}千円）"
               if base.ref_free_cf is not None else "")
        S.append(f"借入金の毎年の返済額が決算書から確かめられず、資金が足りるかどうかを判定できないためである{ref}。"
                 if o is not None else f"借入金の毎年の返済額が決算書から確かめられず、資金が足りるかどうかは判定保留である{ref}。")
    elif base.required_cf:
        S.append(f"借入金を返済すると、資金は年{base.required_cf:,}千円不足する。")
        if o is not None and o.kind == SUFFICIENT:
            S.append(f"審査を通過した改善策（年{acc:,}千円）で、この不足を埋められる見込みとなった。")
        elif o is not None and o.kind == TRIAGE:
            S.append(f"改善策では埋めきれず（なお年{(gap or 0):,}千円不足）、会社をどう残すかの道を選ぶ段階に入った。")
        elif started:
            S.append(f"審査を通過した改善策は年{acc:,}千円で、なお年{(gap or 0):,}千円届いていない。")
    elif base.free_cf is not None:
        S.append(f"借入金を返済した後も資金収支は年{tri(base.free_cf)}千円で、資金の不足は示されていない。")

    if started and not (base.required_cf and o is not None and o.kind in (SUFFICIENT, TRIAGE)):
        runs_, shots_ = _counted_measures(state)
        if runs_ or shots_:
            S.append("審査を通過した主な施策は、" + "、".join(t for t, *_ in (runs_ + shots_)[:2]) + "である。")
        else:
            S.append("審査を通過した改善策はなかった。")

    t = triage(state) if o is not None and o.kind == TRIAGE else None
    todo = [r for r in requests if r.get("status") != "解消"]
    must = [r["item"] for r in todo if r.get("required")]
    if t:
        S.append("示された道は" + "・".join(x.name for x in t.options[:3]) + "で、どれを選ぶかは経営者が決める。")
    elif must:
        S.append("判定を確定させるには、" + "・".join(must[:2]) + "の提出が必要である。")
    elif todo:
        S.append("残るデータ請求は" + "".join(f"「{r['item']}」" for r in todo[:2])
                 + (f"など{len(todo)}件" if len(todo) > 2 else "") + "である。")
    return ["".join(S), ""]


def report_markdown(run) -> str:
    """回次の全データを統合した診断レポート。論争の途中でも、その時点の内容で作る。"""
    from core import adjust, repayment
    from core.ddf import run_status
    from core.digest import load_state, proposals, triage
    from core.guardrails import LEVERS, reconcile
    from core.metrics import PENDING_LABEL, debt_doubt_text, real_adjustments, reference_text, runway_label, tri
    from core.export import SPEAKER_NAMES

    fin = run.financials()
    state = load_state(run)
    base = repayment.cash_base_for(run, fin) if fin is not None else None
    o = outcome(state, base)
    requests = run.read("data_requests.json", [])
    cons = run.read("constraints.json", {"constraints": [], "stops": []}) or {"constraints": [], "stops": []}
    day = (state.messages[-1].at[:10] if state and state.messages and state.messages[-1].at else date.today().isoformat())
    phase = ((o.label + ("" if o.stop_reason == o.kind else f"（止まった理由：{o.stop_reason}）")) if o else
             ("未開始" if state is None or not state.messages else f"進行中：第{state.round}ラウンド（途中経過のレポート）"))

    L = [f"# 経営診断レポート：{_company_name(run)}（{run.meta.label}）", "",
         f"- **診断日**：{day}",
         f"- **診断適格性（DDF）**：{run_status(run)}",
         f"- **結論フェーズ**：{phase}"]
    if state is not None:
        L.append(f"- **診断ミッション**：{state.mission}")
    L.append(f"- **対象決算**：{fin.fiscal_period if fin else '—'}（単位：千円）　回次の状態：{'凍結済み' if run.frozen else '作業中'}")
    if run.frozen:
        L.append(f"- 凍結：{run.meta.frozen_at}")
    L.append("")

    L += ["## 要約", "", *abstract(run, fin, state, base, o, requests)]

    # 1. エグゼクティブサマリー -------------------------------------------------
    L += ["## 1. エグゼクティブサマリー", ""]
    if fin is None or base is None:
        L += ["財務データがないため、資金の診断はできません。", ""]
    else:
        m = live_monitor(state, base) if state is not None else None
        acc = m.accumulated_recovery_cf if m else 0
        shot = m.one_time_cash if m else 0
        runs_, shots_ = _counted_measures(state) if state is not None else ([], [])
        lv = "／".join(m.levers_tried) if m and m.levers_tried else "なし"
        if base.debt_confirmed:
            repay = f"約定返済 年{base.debt_service:,}千円（人間が返済予定表で確定）"
        elif base.debt_unverified:
            repay = "約定返済は決算書から確かめられない（BS記載に疑問あり、確認が必要）"
        else:
            repay = f"約定返済 年{base.debt_service:,}千円"
        s = (f"簡易営業CFは年{tri(base.simple_cf)}千円、{repay}で、返済後の資金収支は年{tri(base.free_cf)}千円"
             + ("（確かめられない返済を0とした値）" if base.shortage_pending else "") + "である。")
        if base.shortage_pending:
            s += f"資金不足の有無は{PENDING_LABEL}。{reference_text(base)}。"
        elif base.required_cf:
            s += f"必要CFは年{base.required_cf:,}千円。"
        else:
            s += "資金の不足は示されていない。"
        if state is not None and state.messages:
            s += (f"審査を通過し資金が尽きる前に効く継続改善CFは年{acc:,}千円（試したレバー：{lv}）、"
                  f"一括調達（一時的資金）は{shot:,}千円。")
            if m and m.gap is not None and base.required_cf and not base.shortage_pending:
                s += ("通過した改善策で必要CFを満たした。" if m.gap == 0 else f"必要CFには年{m.gap:,}千円届いていない。")
            rw0 = runway_label(m.base_runway_months, base.free_cf, short=True, pending=base.shortage_pending)
            rw1 = runway_label(m.cash_runway_months, base.free_cf + acc if base.free_cf is not None else None,
                               short=True, pending=base.shortage_pending)
            s += f"残余月数は{rw0}→{rw1}。"
        L += [s, ""]
        if runs_:
            L += ["主たる施策：" + "、".join(f"{t}（年{v:,}千円）" for t, v, _ in runs_[:3]), ""]
        if o is not None:
            L += [f"結論：**{o.label}**" + ("" if o.stop_reason == o.kind else f"（止まった理由：{o.stop_reason}）"), ""]
        t = triage(state) if state is not None else None
        if t:
            L += ["トリアージで宣告された道（選ぶのは人間）：", *[f"- {x.name}：残す＝{'・'.join(x.keep) or '—'}、"
                                                            f"捨てる＝{'・'.join(x.discard) or '—'}、前提＝{'／'.join(x.preconditions) or '—'}"
                                                            for x in t.options]]
            if state.adopted_option:
                L.append(f"- **採択の記録**：{state.adopted_option}" + (f"（{state.adopted_note}）" if state.adopted_note else ""))
            L.append("")
        judge = [x for x in (state.messages if state else []) if x.speaker == "judge" and x.judge_note and x.judge_note.summary]
        if judge:
            L += [f"> Moderator Judge の総括（第{judge[-1].round}ラウンド。LLM による論点整理で、判定はプログラムが行う）："
                  f"{_clip(judge[-1].judge_note.summary, 400)}", ""]

    # 2. 前提条件と監査的オーバーライド ---------------------------------------
    L += ["## 2. 前提条件と監査的オーバーライド（人間介入）", ""]
    if fin is not None:
        auto = [a for a in real_adjustments(fin) if a.origin == "開示"] if not _raises(real_adjustments, fin) else []
        adj = adjust.load(run)
        L.append("- **実質化の調整（B/S時価修正。資金の計算は変えない）**：" + ("なし" if not (auto or adj) else ""))
        L += [f"  - 〔決算書の開示から自動〕{a.describe()}" for a in auto]
        L += [f"  - 〔人間 {a.id}〕{a.describe()}" + (f"　入力：{a.at}" if a.at else "") for a in adj]
        rp = repayment.load(run)
        if rp is not None:
            L.append(f"- **約定返済額の確定**：{rp.describe()}　確定日時：{rp.at}"
                     "（資金の監視はこの額で計算。決算書の数字は変えていない）")
        elif base is not None and base.debt_unverified:
            L.append(f"- **約定返済額の確定**：未確定。{debt_doubt_text(base)}。資金不足の有無は{PENDING_LABEL}")
        else:
            L.append("- **約定返済額の確定**：不要（決算書の区分どおり）")
        if fin.rounding_adjustments:
            total = sum(abs(a.amount) for a in fin.rounding_adjustments)
            L.append(f"- **未解明差異の承認（DDF条件付き適格）**：{total:,}千円 → "
                     + "、".join(f"{a.check} {a.amount:+,}（{a.booked_to}）" for a in fin.rounding_adjustments))
    humans = [x for x in (state.messages if state else []) if x.speaker == "human"]
    if humans:
        L.append("- **論争への介入（ライム）**：")
        L += [f"  - 第{x.round}ラウンド：{_clip(x.text, 160)}" for x in humans]
    if cons.get("constraints"):
        L.append("- **制約・前提条件**：" + "／".join(cons["constraints"]))
    L.append("")

    # 3. 採択された改善シナリオ -------------------------------------------------
    L += ["## 3. 採択された改善シナリオ一覧", "",
          "審査を通過し、資金が尽きる前に効くとプログラムが数えた施策（実行するかは経営者が決める）。", ""]
    props = proposals(state) if state is not None else []
    counted = [p for p in props if p.status in ("審査通過・時期内", "一部のみ間に合う", "減額採択")]
    rec_rows, shot_rows = [], []
    for p in counted:
        for b in p.bridges:
            if b.in_time is False or b.cf_effect == 0:
                continue
            row = (f"| {p.title} | {b.label}（{b.direction}） | {b.cf_effect:+,} | {b.lead_months}か月後 | "
                   f"{SPEAKER_NAMES.get(p.speaker, p.speaker)} 第{p.round}ラウンド | {p.status} |")
            (rec_rows if b.recurring else shot_rows).append(row)
    head = "| 施策 | 科目 | 資金効果（千円） | 効き始め | 提案 | 扱い |\n|---|---|---:|---|---|---|"
    L += ["### 【継続改善CF（年）】"] + ([head, *rec_rows] if rec_rows else ["なし"])
    L += ["", "### 【一括調達（一時的資金）】"] + ([head, *shot_rows] if shot_rows else ["なし"])
    reduced = _reductions(state) if state is not None else []
    if reduced:
        L += ["", "### 減額採択（▽）", *reduced]
    L.append("")

    # 4. 残されたリスク・未決争点 -------------------------------------------------
    L += ["## 4. 残されたリスク・未決争点", ""]
    if state is None or not state.messages:
        L += ["論争はまだ始まっていない。", ""]
    rejected = [p for p in props if p.status == "棄却"]
    late = [p for p in props if p.status == "審査通過・時期外"]
    if rejected:
        L += ["**退けられた・差し戻された提案**", *[f"- {p.message_id} {p.title}：{_clip(p.reason, 100)}" for p in rejected], ""]
    if late:
        L += ["**審査は通ったが、資金が尽きた後に効く提案**", *[f"- {p.message_id} {p.title}" for p in late], ""]
    att = _attacks(state) if state is not None else []
    if att:
        L += ["**Dr. Rebuild の反論（攻撃）とその扱い**", *att, ""]
    if state is not None:
        untried = [lv for lv in LEVERS if lv not in live_monitor(state, base).levers_tried] if base else []
        L.append("**未着手のレバー**：" + ("／".join(untried) if untried else "なし（4つすべて試した）"))
        open_agenda = [a for a in state.agenda if a.status != "決着"]
        if open_agenda:
            L += ["", "**決着していない論点**", *[f"- {a.id} {a.title}［{a.status}］" for a in open_agenda]]
    if base is not None:
        L += ["", "**計算上の留保**", "- 設備投資は資金の計算に含めていない（楽観側）"]
        if any("未取得のため0" in x and "dep" in x for x in base.basis):
            L.append("- 減価償却費が書類から取り出せていないため0で計算している（資金は少なめ＝保守側）")
    L.append("")

    # 5. データ請求（宿題リスト） -----------------------------------------------
    L += ["## 5. データ請求（宿題リスト）", ""]
    done = [r for r in requests if r.get("status") == "解消"]
    todo = [r for r in requests if r.get("status") != "解消"]
    L.append("**解消済み**" + ("：なし" if not done else ""))
    for r in done:
        how = "、".join(f"{v['label']} {v['cur']:,}（{(v.get('source') or {}).get('file') or '—'}）"
                        for v in r.get("resolved_by", []))
        L.append(f"- {r['id']} {'【必須】' if r.get('required') else ''}{r['item']}：解消" + (f"　証跡：{how}" if how else ""))
    L += ["", "**未解決**" + ("：なし" if not todo else "")]
    for r in todo:
        L.append(f"- {r['id']} {'【必須】' if r.get('required') else ''}{r['item']}：{r['status']}　"
                 f"請求先：{r['request_to']}　解消する争点：{r['resolves']}")
    L.append("")

    # 付録 ----------------------------------------------------------------------
    L += ["## 付録", ""]
    if fin is not None:
        rep = reconcile(fin)
        L.append(f"- 検算ゲート：全{rep.total}項目　一致{rep.count('一致')}　不一致{rep.count('不一致')}　"
                 f"未確認{rep.count('未確認')}（端数差{rep.rounding_diffs}件は許容差内）")
    if base is not None:
        L += ["- 資金の計算根拠：", *[f"  - {x}" for x in base.basis]]
    tree = run.read("decision_tree.json", {"nodes": []}) or {"nodes": []}
    if tree.get("nodes"):
        L += ["- （参考）旧・静的分析のシナリオ採否：",
              *[f"  - {n['id']} {n['label']}：{n['status']}　— {n['reason']}（{n['source']}）" for n in tree["nodes"]]]
    L += ["", "---", "このレポートは DiaDoc が回次の記録（読み取った財務データ、論争の判定、人間の介入、データ請求）から"
          "プログラムで組み立てたものである。判定と数字はプログラムの計算による。"]
    return "\n".join(x for x in L if x is not None) + "\n"


def _raises(fn, *a) -> bool:
    try:
        fn(*a)
    except ValueError:
        return True
    return False


def _reductions(state) -> list[str]:
    """減額採択された提案：元の資金効果、減額後、理由（Rebuild の指摘）。"""
    from tools.standard_accounts import LABELS

    last: dict[str, object] = {}
    for r in state.rulings:
        last[r.message_id] = r
    by_id = {m.id: m for m in state.messages}
    out = []
    for mid, r in last.items():
        if not r.reduced or mid not in by_id:
            continue
        m = by_id[mid]
        pairs = [f"{LABELS.get(o.account, o.account)} {o.cf_effect:,} → {n.cf_effect:,}"
                 for o, n in zip(m.bridges, r.adjusted_bridges) if o.cf_effect != n.cf_effect]
        why = r.reasons[0] if r.reasons else ""
        out.append(f"- {mid} {(m.headline or '').strip() or _clip(m.text, 40)}：{'、'.join(pairs)}（千円・年）　理由：{_clip(why, 160)}")
    return out
