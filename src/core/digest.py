"""画面のパネルに出す要約を、論争の状態と回次の記録から決定論的に作る（LLM は使わない）。

同じ状態からは必ず同じ要約が出る。画面の各部品はここを通して状態を読む。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.runs import input_title
from schema import TriageOption

FINANCIAL_SUFFIXES = (".pdf", ".xlsx", ".xls", ".csv", ".png", ".jpg", ".jpeg")
QUALITATIVE_SUFFIXES = (".md", ".txt")
_ADDED = re.compile(r"資料「(.+?)」を追加しました")


# ---------------------------------------------------------------------------
# 資料
# ---------------------------------------------------------------------------
@dataclass
class DocEntry:
    name: str
    kind: str            # 財務／定性／検算表／資料
    origin: str          # どの回次で、どう入ったか
    citable: bool        # エージェントが出典として引用できるか
    added_round: int | None = None   # 議論の途中で追加されたラウンド
    path: object = None              # 回次フォルダ内のファイル（財務データの出典書類は原本がないので None）
    url: str | None = None           # 公開元の URL（有価証券報告書など）


def _kind(filename: str, title: str = "") -> str:
    """資料の種類。拡張子ではなく中身の名前で見る（Excel の財務諸表を「検算表」と呼ばない）。"""
    from core.mock_engine import classify

    n = filename.lower()
    if n.endswith(QUALITATIVE_SUFFIXES):
        return "定性"
    if "検算" in title or "検算" in filename:
        return "検算表"
    if classify(title or filename).startswith("財務諸表") or classify(filename).startswith("財務諸表"):
        return "財務"
    return "資料"


def documents(run, ctx, state=None) -> list[DocEntry]:
    """投入済みの資料。財務データの出典書類、回次の投入ファイル（親の回次から引き継いだものを含む）。"""
    added: dict[str, int] = {}
    if state is not None:
        for m in state.messages:
            if m.speaker == "human":
                hit = _ADDED.search(m.text)
                if hit:
                    added[hit.group(1)] = m.round
    out: list[DocEntry] = []
    seen: set[str] = set()
    chain, r = [], run
    while r is not None:
        chain.append(r)
        r = r.parent()
    files = []   # （回次, ファイル, 表示名）古い回次から
    for r in reversed(chain):
        files += [(r, p, input_title(p)) for p in r.inputs() if p.name != "financials.json"]
    used: set = set()
    src = run.financials_source()
    if ctx.fin is not None:
        where = "この回次" if src is None or src.run_id == run.run_id else f"{src.meta.label}から引き継ぎ"
        for name, info in ctx.fin.documents.items():
            # 財務データの出典書類が投入ファイルそのものなら、1行にまとめる（同じ Excel を2回並べない）
            hit = next(((r, p) for r, p, t in reversed(files) if p not in used and name in (p.name, t)), None)
            if hit:
                used.add(hit[1])
            out.append(DocEntry(name=name, kind="財務", origin=f"財務データの出典書類（{where}）", citable=True,
                                url=(info or {}).get("url"), path=hit[1] if hit else None))
            seen.add(name)
    for r, p, title in files:
        if p in used or title in seen:
            continue
        seen.add(title)
        label = "この回次" if r.run_id == run.run_id else f"{r.meta.label}から引き継ぎ"
        rnd = added.get(title)
        origin = f"議論の途中で追加（第{rnd}ラウンド）" if rnd else label
        out.append(DocEntry(name=title, kind=_kind(p.name, title), origin=origin, citable=title in ctx.registry,
                            added_round=rnd, path=p))
    return out


def gate_headline(record: dict) -> str:
    """検算ゲートの見出し。修正前の読み取り記録（複数の差額を「差額」とだけ書いたもの）も、件数と内訳付きで出し直す。"""
    from core.materiality import TO_THOUSAND

    m = record.get("materiality") or {}
    head = m.get("headline", "")
    fails = [f for f in record.get("failed_checks") or [] if f.get("diff") is not None]
    if len(fails) <= 1 or head.startswith("差額合計") or m.get("total_diff_thousand") is None:
        return head
    scale = TO_THOUSAND.get(((record.get("financials") or {}).get("unit")) or "千円", 1.0)
    parts = sorted(fails, key=lambda f: -abs(f["diff"]))
    items = "・".join(f"{f['name']}{'（前期）' if f.get('period') == '前期' else ''} {abs(f['diff']) * scale:,.0f}"
                      for f in parts[:3])
    more = f"ほか{len(parts) - 3}件" if len(parts) > 3 else ""
    pct = "—" if m.get("pct_assets") is None else f"{m['pct_assets']:.3%}"
    return f"差額合計: {m['total_diff_thousand']:,.0f}千円（{len(parts)}件：{items}{more}）、総資産の{pct}"


def dropped_explaining(record: dict) -> list[str]:
    """読み取れずに捨てた行のうち、検算の不一致を説明できそうなもの（その金額が差額に等しい、または合計が等しい）。

    画面で「読み取れなかったことによる可能性」と注意するのは、この一覧が空でないときだけにする。
    """
    from tools.file_ingest import is_reference_line

    rows = [r for r in ((record.get("report") or {}).get("dropped_values") or [])
            if r.get("cur") is not None and not is_reference_line(r.get("label"), r.get("section"))]
    fails = [(abs(f["diff"]), f.get("tolerance") or 0) for f in record.get("failed_checks") or []
             if f.get("period") == "当期" and f.get("diff") is not None]
    hits = [r["label"] for r in rows if any(abs(abs(r["cur"]) - d) <= t for d, t in fails)]
    if not hits and rows:
        total = sum(abs(r["cur"]) for r in rows)
        if any(abs(total - d) <= t for d, t in fails):
            hits = [r["label"] for r in rows]
    return hits


def decode_text(content: bytes) -> str:
    """テキスト資料の文字コードを推定して読む（UTF-8、なければ Windows の Shift_JIS）。"""
    for enc in ("utf-8-sig", "cp932"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 検討ステータス
# ---------------------------------------------------------------------------
@dataclass
class TriageSummary:
    message_id: str
    round: int
    options: list[TriageOption]


def triage(state) -> TriageSummary | None:
    """審査を通過した最新のトリアージ宣告。なければ None。"""
    if state is None:
        return None
    passed = {r.message_id for r in state.rulings if r.verdict == "通過"}
    for m in reversed(state.messages):
        if m.action == "宣告" and m.id in passed and m.options:
            return TriageSummary(message_id=m.id, round=m.round, options=m.options)
    return None


# ---------------------------------------------------------------------------
# 採否ステータスとボトルネック（右パネル）
# ---------------------------------------------------------------------------
@dataclass
class BridgeLine:
    account: str
    label: str
    direction: str
    cf_effect: int
    lead_months: int
    recurring: bool
    in_time: bool | None     # None は審査前（数えていない）


@dataclass
class ProposalStatus:
    message_id: str
    speaker: str
    round: int
    title: str               # 見出し（エージェントの見出し、なければ最初の一文。切り詰めない）
    status: str              # 審査通過・時期内／一部のみ間に合う／審査通過・時期外／棄却／審理中（採用は人間の「採択の記録」だけ）
    reason: str
    bridges: list[BridgeLine]
    body: str = ""           # 提案の本文（全文）


def _title(text: str) -> str:
    """見出しのない古い記録は、最初の一文をそのまま見出しにする（切り詰めず、画面で折り返す）。"""
    return re.split(r"(?<=[。！？])|\n", text.strip(), maxsplit=1)[0].strip()


def proposals(state) -> list[ProposalStatus]:
    """改善案（Growth・Rebuild の「提案」）ごとの採否。判定と監視指標から決定論的に決める。"""
    from tools.standard_accounts import LABELS

    if state is None:
        return []
    verdict = {}
    reasons = {}
    adjusted = {}
    for r in state.rulings:
        verdict[r.message_id] = r.verdict
        reasons[r.message_id] = r.reasons[0] if r.reasons else ""
        adjusted[r.message_id] = r.adjusted_bridges
    counted = {(c.message_id, id(c)): c for c in state.monitor.counted}
    by_msg: dict[str, list] = {}
    for c in counted.values():
        by_msg.setdefault(c.message_id, []).append(c)
    out = []
    for m in state.messages:
        if m.action != "提案" or m.speaker not in ("growth", "rebuild"):
            continue
        v = verdict.get(m.id)
        cs = by_msg.get(m.id, [])
        lines = []
        shown = adjusted.get(m.id) if v == "通過" and adjusted.get(m.id) is not None else m.bridges
        for i, b in enumerate(shown):
            in_time = cs[i].in_time if v == "通過" and i < len(cs) else None
            lines.append(BridgeLine(b.account, LABELS.get(b.account, b.account), b.direction, b.cf_effect,
                                    b.lead_months, b.recurring, in_time))
        if v is None:
            status, why = "審理中", "Judge の審査前"
        elif v != "通過":
            status, why = "棄却", reasons.get(m.id, "")
        else:
            flags = [x.in_time for x in lines if x.cf_effect > 0]
            if adjusted.get(m.id) is not None:
                status, why = "減額採択", reasons.get(m.id, "反論を受けて資金効果を減らして数える")
            elif flags and all(flags):
                status, why = "審査通過・時期内", "審査を通り、資金が尽きる前に効く（採用するかは人間が決める）"
            elif any(flags):
                status, why = "一部のみ間に合う", "資金が尽きる前に効くのは一部だけ"
            else:
                status, why = "審査通過・時期外", "審査は通ったが、効果が出るのは資金が尽きた後"
        out.append(ProposalStatus(m.id, m.speaker, m.round, (m.headline or "").strip() or _title(m.text), status, why,
                                  lines, body=m.text))
    return out


@dataclass
class Bottleneck:
    kind: str       # 資金／時期／根拠／前提
    text: str


def bottlenecks(state, base) -> list[Bottleneck]:
    """いま議論を止めているもの。資金の不足、間に合わない手、差し戻しの理由、前提条件。"""
    out: list[Bottleneck] = []
    m = state.monitor if state is not None else None
    req = base.required_cf
    if req is None:
        out.append(Bottleneck("資金", "現金預金か経常利益がなく、資金の判定ができない（データ請求が必要）"))
    elif req > 0:
        gap = m.gap if m else req
        acc = m.accumulated_recovery_cf if m else 0
        rw = m.cash_runway_months if m else None
        out.append(Bottleneck("資金", f"返済後の資金収支が年{req:,}千円の不足。通過した改善で{acc:,}千円を埋め、"
                                      f"残り{gap:,}千円" + (f"（残余約{rw:.1f}か月）" if rw is not None else
                                                          "（10年のうちに資金は尽きない：資金ショートリスク解消）" if m else "")))
    else:
        out.append(Bottleneck("資金", "返済後の資金収支はプラスで、資金の不足はない。争点は資金以外にある"))
    if state is None:
        return out
    for p in proposals(state):
        for b in p.bridges:
            if b.in_time is False:
                rw = state.monitor.cash_runway_months
                out.append(Bottleneck("時期", f"{b.label}の{b.direction}（{b.lead_months}か月後）は資金が尽きた後に効く"
                                              + ("" if rw is None else f"（残余約{rw:.1f}か月）")))
        if p.status == "棄却":
            out.append(Bottleneck("根拠", f"{p.title}：{p.reason}"))
    tri = triage(state)
    if tri:
        for o in tri.options:
            if o.preconditions:
                out.append(Bottleneck("前提", f"{o.name}：{o.preconditions[0]}"))
    return out


def mentioned_accounts(state) -> set[str]:
    """通過した因果ブリッジで触れられた科目（KPIカードに「議論中」の印を付ける）。"""
    if state is None:
        return set()
    return {b.account for _, b in state.passed_bridges()}


def comparison(state):
    """最新の「道の比較」（Judge）。なければ None。"""
    if state is None:
        return None
    for m in reversed(state.messages):
        if m.action == "比較" and m.comparison:
            return m
    return None


def document_items(fin, doc_name: str) -> list[dict]:
    """財務データのうち、その書類を出典とする科目（出典頁付き）。プレビューの表に使う。"""
    if fin is None:
        return []
    rows = []
    for key, it in fin.items.items():
        if it.source.file != doc_name:
            continue
        rows.append({"表": it.statement, "区分": it.section, "標準科目": it.label, "原資料の科目名": it.source_label,
                     "前期": it.prev, "当期": it.cur, "頁": it.source.page or "", "key": key})
    order = {"BS": 0, "PL": 1, "製造原価": 2, "売上原価調整": 3, "販管費内訳": 4, "株主資本等変動": 5}
    return sorted(rows, key=lambda r: (order.get(r["表"], 9), int(r["頁"]) if str(r["頁"]).isdigit() else 999))


# ---------------------------------------------------------------------------
# 回次の比較
# ---------------------------------------------------------------------------
PHASE_LABEL = {"exploration": "探索", "triage_ready": "トリアージ", "settlement": "決着"}


def load_state(run):
    """回次の論争の状態を読むだけで取り出す（チェックポイントがなければ None）。"""
    from core.graph import DebateSession

    if not (run.path / DebateSession.DB_NAME).exists():
        return None
    s = DebateSession(run, readonly=True)
    try:
        return s.state() if s.started else None
    finally:
        s.close()


def run_summary(run) -> dict:
    """回次の結論の要点（経営判断に効くものだけ）。"""
    st = load_state(run)
    meta = run.meta
    head = {"回次": f"{meta.label}（{meta.as_of}）", "状態": "凍結" if run.frozen else "作業中"}
    if st is None:
        return head | {"診断ミッション": "—", "論争": "未開始"}
    m = st.monitor
    from core.metrics import net_after_improvement, runway_label

    rw0 = runway_label(m.base_runway_months, m.base.free_cf, short=True)
    rw1 = runway_label(m.cash_runway_months, net_after_improvement(m), short=True)
    req = "—" if m.base.required_cf is None else f"{m.base.required_cf:,}"
    cands = [p.title for p in proposals(st) if p.status in ("審査通過・時期内", "一部のみ間に合う", "減額採択")]
    tri = triage(st)
    cmp_ = comparison(st)
    ways = "—"
    if tri:
        by = {a.name: a for a in cmp_.comparison} if cmp_ else {}
        ways = "／".join(o.name + ("" if o.name not in by or by[o.name].in_time is None else
                                   ("（間に合う）" if by[o.name].in_time else "（残余月数を超える）")) for o in tri.options)
    return head | {
        "診断ミッション": st.mission,
        "論争": f"第{st.round}ラウンド・発言{len(st.messages)}件",
        "試した改善レバー": "・".join(m.levers_tried) or "なし",
        "最終フェーズ": PHASE_LABEL.get(st.phase, st.phase) + (f"（{st.stop_reason}）" if st.stop_reason else "（進行中）"),
        "残余月数": f"{rw0} → {rw1}",
        "回収CF累計／必要CF（年・千円）": f"{m.accumulated_recovery_cf:,}／{req}",
        "残りの不足（年・千円）": "—" if m.gap is None else f"{m.gap:,}",
        "審査通過・時期内の改善案": "／".join(cands) or "なし",
        "宣告された道（Level 0）": ways,
        "採択された方針": st.adopted_option + (f"（{st.adopted_note}）" if st.adopted_note else "")
        if st.adopted_option else ("未記録（人間が選ぶ）" if tri else "—"),
    }


COMPARE_ROWS = ("回次", "状態", "診断ミッション", "論争", "試した改善レバー", "最終フェーズ", "残余月数",
                "回収CF累計／必要CF（年・千円）", "残りの不足（年・千円）", "審査通過・時期内の改善案", "宣告された道（Level 0）",
                "採択された方針")


def compare_runs(runs) -> list[dict]:
    """回次ごとの要点を、物差しの行にそろえて返す（1行＝1つの物差し、列＝回次）。"""
    sums = [run_summary(r) for r in runs]
    return [{"物差し": k, **{s["回次"]: s.get(k, "—") for s in sums}} for k in COMPARE_ROWS if k != "回次"]
