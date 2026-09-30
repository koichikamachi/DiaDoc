"""バックエンド（LangGraph）未接続時のモック・エンジン。

論争の台詞は台本だが、次の部分は本物の決定論的ロジックを使う。
- 検算ゲート（core.guardrails.reconcile）
- 形式審査（core.guardrails.review_claim）
- 回次の凍結と引き継ぎ（core.runs）

投入資料の中身（数値）の読み取りは未実装。ファイル名から資料の種別を判定し、
対応するデータ請求を「受領（検証待ち）」に進めるところまでを行う。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import config
from core import metrics
from core.guardrails import reconcile, review_claim
from core.runs import Run, input_title, latest_run, list_runs, now_iso, start_next_run
from schema import Claim, SourceRef

DOC = "有報第73期"


def _src(*pages: str) -> list[dict]:
    return [{"file": DOC, "page": p} for p in pages]


def _msg(who: str, phase: str, text: str, sources=None, claim=None, ruling=None) -> dict:
    return {"id": uuid.uuid4().hex[:8], "at": now_iso(), "who": who, "phase": phase, "text": text,
            "sources": sources or [], "claim": claim, "ruling": ruling}


# ---------------------------------------------------------------------------
# 形式審査（メッセージ単位）
# ---------------------------------------------------------------------------
def review_message(m: dict):
    """主張を含むメッセージを形式審査する。主張がなければ None。"""
    c = m.get("claim")
    if not c:
        return None
    return review_claim(Claim(speaker=m["who"], text=c.get("text", ""),
                              sources=[SourceRef(**s) for s in m.get("sources", [])],
                              settle_condition=c.get("settle_condition")))


# ---------------------------------------------------------------------------
# 第1次分析の初期状態（サンプル作成用）
# ---------------------------------------------------------------------------
def seed_initial_run(run: Run) -> None:
    fin = run.financials()
    rep = reconcile(fin)
    m = metrics.core_metrics(fin)
    nom, real = metrics.balance_sheet(fin, "nominal"), metrics.balance_sheet(fin, "real")

    debate = [
        _msg("radar", "検算",
             f"検算ゲートを実行しました。全{rep.total}項目のうち一致{rep.count('一致')}、不一致{rep.count('不一致')}です"
             f"（端数差{rep.rounding_diffs}件は許容差内）。主要数値を提示します。単体の営業利益率は{m['営業利益率']:.1%}、"
             f"経常利益{fin.value('ord') / 1e5:.1f}億円のうち受取配当金が{fin.value('div') / 1e5:.1f}億円（{m['配当依存度']:.0%}）を占めます。",
             _src("93")),
        _msg("rebuild", "診断",
             f"本業の稼ぐ力は薄い。株式の含み益を除いた実質BSで見れば、営業利益ROAは{real['営業利益ROA']:.1%}にとどまる。"
             "原料米の高止まりが続けば営業赤字に転じる。不採算品目の即時整理を主張する。",
             _src("93", "25"), {"text": "不採算品目の即時整理", "settle_condition": "品目別粗利でマイナスの品目が存在するか"}),
        _msg("growth", "診断",
             f"縮小均衡には反対だ。単体売上は{m['売上高成長率']:.1%}増えた。主力商品の定番化と価格改定の浸透が効いている。"
             "TOP6＋2への集中と価格転嫁で、稼ぐ力は取り戻せる。",
             _src("24"), {"text": "増収は自社ブランド力の表れ", "settle_condition": None}),
        _msg("radar", "診断",
             f"事実を補足します。当期の商品仕入高は{m['当期商品仕入高'] / 1e5:.1f}億円で、前期の{m['前期商品仕入高'] / 1e5:.2f}億円から急増しています。"
             "増収の大半は、関連会社経由の輸入商品の販売による可能性があります。",
             _src("94", "24")),
        _msg("judge", "形式審査",
             "Prof. Growth の「増収は自社ブランド力の表れ」は、決着条件が示されていません。差し戻します。"
             "自社製品と仕入商品の売上を分けたとき、何が観察されれば主張が成り立つかを示してください。",
             ruling="差し戻し"),
        _msg("growth", "診断",
             "決着条件を示す。仕入商品を除いた自社製品売上が前期を上回り、うるち主力品の粗利率が前期以上なら、価格転嫁は機能している。",
             _src("23"), {"text": "価格転嫁は機能している", "settle_condition": "自社製品売上の前期比と主力品粗利率"}),
        _msg("judge", "形式審査", "形式審査を通過しました。ただし製品別の売上・粗利は有報に開示がありません。データ請求 R3 として登録します。",
             ruling="通過"),
        _msg("rebuild", "診断", "最悪の場合に備え、法的整理（民事再生）も選択肢として残しておくべきだ。",
             claim={"text": "民事再生を選択肢に残す", "settle_condition": None}),
        _msg("radar", "診断",
             f"法的整理の前提を確認しました。有利子負債は約{m['有利子負債'] / 1e5:.1f}億円、現預金は{m['現金預金'] / 1e5:.1f}億円、"
             f"自己資本比率は{nom['自己資本比率']:.1%}です。債務超過でも資金繰りの破綻でもありません。",
             _src("91", "92")),
        _msg("judge", "審理", "民事再生シナリオを棄却します。根拠は Analyst Radar の提示した財政状態です。", _src("91", "92"), ruling="棄却"),
        _msg("radar", "データ請求",
             "広告宣伝費と販売促進費が単体の注記で確認できていません。価格転嫁の議論に必要なため、追加データを請求します（R1・R2）。"
             "あわせて、その他流動資産に埋もれている仮払金等の内訳を請求します（R4）。",
             _src("93"), ruling="保留"),
        _msg("judge", "暫定整理",
             "暫定整理です。全事業・全品目維持は棄却、即時民事再生は棄却、コア事業集中＋不採算撤退は条件付きで採用候補とし、"
             "品目別粗利と販促費のデータ到着まで保留します。",
             ruling="保留"),
    ]
    tree = {
        "root": "第73期モデル：経営課題への処方",
        "nodes": [
            {"id": "A", "parent": None, "label": "全事業・全品目維持", "status": "棄却",
             "reason": f"営業利益率{m['営業利益率']:.1%}。材料費が製造費用の{m['材料費比率']:.1%}を占め、原料米高騰を価格転嫁だけで吸収できる根拠がない",
             "source": "有報第73期 p.93–94"},
            {"id": "B", "parent": None, "label": "即時民事再生", "status": "棄却",
             "reason": f"法的整理の前提を欠く。有利子負債約{m['有利子負債'] / 1e5:.1f}億円、現預金{m['現金預金'] / 1e5:.1f}億円、自己資本比率{nom['自己資本比率']:.1%}",
             "source": "有報第73期 p.91–92"},
            {"id": "C", "parent": None, "label": "コア事業集中＋不採算撤退", "status": "条件付き採用",
             "reason": f"本業の営業利益ROAは名目{nom['営業利益ROA']:.1%}、実質{real['営業利益ROA']:.1%}。集中による改善余地あり。ただし不採算品目の特定に品目別粗利が必要",
             "source": "有報第73期 p.8, p.93"},
            {"id": "C1", "parent": "C", "label": "TOP6＋2への集中", "status": "採用候補",
             "reason": "会社の中期経営計画と整合", "source": "有報第73期 p.8"},
            {"id": "C2", "parent": "C", "label": "不採算品目の生産終了", "status": "保留",
             "reason": "品目別粗利が未取得（R3 請求中）", "source": "—"},
            {"id": "C3", "parent": "C", "label": "不採算部門のカーブアウト（売却）", "status": "保留",
             "reason": "売却対象となる独立部門の有無が未確認", "source": "—"},
            {"id": "C4", "parent": "C", "label": "人員削減による固定費圧縮", "status": "保留",
             "reason": "年齢構成・工場別人員の資料待ち", "source": "—"},
        ],
    }
    requests = [
        {"id": "R1", "item": "広告宣伝費", "status": "請求中", "request_to": "販売費及び一般管理費の内訳（単体注記 p.98以降）",
         "resolves": "価格転嫁は広告投資の効果か／TVCMの費用対効果", "doc_type": "販管費内訳", "received": []},
        {"id": "R2", "item": "販売促進費", "status": "請求中", "request_to": "販売費及び一般管理費の内訳（単体注記 p.98以降）",
         "resolves": "定番化による販促費抑制は本当か（有報 p.24の説明の検証）", "doc_type": "販管費内訳", "received": []},
        {"id": "R3", "item": "製品別売上・粗利", "status": "請求中", "request_to": "管理会計資料（品目別損益）",
         "resolves": "どの品目が不採算か／増収は自社製品か仕入商品か", "doc_type": "品目別損益", "received": []},
        {"id": "R4", "item": "仮払金・未収入金等の内訳", "status": "請求中", "request_to": "勘定科目内訳明細書",
         "resolves": "その他流動資産の中身（数字の信用度の関門）", "doc_type": "勘定科目内訳明細書", "received": []},
    ]
    run.write("debate_log.json", debate)
    run.write("decision_tree.json", tree)
    run.write("data_requests.json", requests)
    run.write("constraints.json", {"constraints": [], "stops": []})
    refresh_derived(run)


# ---------------------------------------------------------------------------
# 人間介入（テキスト）
# ---------------------------------------------------------------------------
INTERVENTION_RULES = [
    {
        "any": ["売却", "カーブアウト", "手放"],
        "neg": ["不可", "しない", "禁止", "避け", "NG", "だめ", "ダメ", "反対"],
        "constraint": "事業売却・カーブアウトは不可", "stop_reason": "価値判断",
        "tree": {"C3": ("制約により除外", "操作者の制約：事業売却は不可")},
        "new_request": {"id": "R5", "item": "工場別の稼働率と固定費", "request_to": "工場別損益・稼働実績",
                        "resolves": "ライン集約による止血の効果", "doc_type": "工場別資料"},
        "responses": [
            ("judge", "制約として登録します。事業売却・カーブアウトを含むシナリオを除外します。止まり方の分類は「価値判断」です。", "登録"),
            ("rebuild", "承知した。売却は外す。その代わり、止血は内側で行う。不採算品目の生産終了と、ラインの集約で固定費を落とすべきだ。"
                        "外科手術はできなくとも、切除はできる。", None),
            ("growth", "制約は歓迎する。売らないなら、育てる前提で議論できる。品目を絞った分の生産能力を、TOP6＋2と海外向け（BEIKA）に振り向けるべきだ。", None),
            ("radar", "ライン集約の効果を測るため、工場別の稼働率と固定費の内訳を請求します（R5）。有報で分かるのは工場別の帳簿価額と従業員数までです。", None),
        ],
    },
    {
        "any": ["雇用", "人員", "リストラ", "解雇", "従業員"], "neg": [],
        "constraint": "人員削減は行わない（雇用維持）", "stop_reason": "価値判断",
        "tree": {"C4": ("制約により除外", "操作者の制約：雇用維持")},
        "new_request": {"id": "R6", "item": "年齢構成・工場別人員", "request_to": "人事資料",
                        "resolves": "自然減による人件費調整の見込み", "doc_type": "人事資料"},
        "responses": [
            ("judge", "制約として登録します。人員削減を伴うシナリオを除外します。止まり方の分類は「価値判断」です。", "登録"),
            ("rebuild", "ならば人件費は自然減と配置転換で調整する。省人化投資は、人を増やさずに増産をこなすことで回収する。", None),
            ("growth", "賛成だ。浮いた人手を、品質保証と海外向けの商品開発に回せる。", None),
            ("radar", "平均勤続年数16.9年、平均年齢43.7歳です（有報 p.60）。自然減の見込みを立てるため、年齢構成の資料を請求します（R6）。", None),
        ],
    },
    {
        "any": ["価格", "値上げ", "値下げ", "転嫁"], "neg": [],
        "constraint": "価格政策を論点として優先する", "stop_reason": None, "tree": {}, "new_request": None,
        "responses": [
            ("judge", "論点の優先順位を変更します。価格政策を先に審理します。", "登録"),
            ("growth", "国産米100%という差別化があるからこそ、価格転嫁の余地はある。値上げ後の販売数量の推移を見れば判定できる。", None),
            ("rebuild", "有報自身が「他社に比べやや割高なコスト構造」と認めている（p.15）。値上げの余地より、原価の方を先に見るべきだ。", None),
            ("radar", "値上げ前後の品目別販売数量を請求します。流通側の値引き・リベートは返金負債6.5億円として計上されています（p.92）。", None),
        ],
    },
]


def apply_intervention(run: Run, text: str) -> list[dict]:
    """テキスト介入を処理し、開いている回次に記録する。追加されたメッセージを返す。"""
    text = text.strip()
    debate = run.read("debate_log.json", [])
    tree = run.read("decision_tree.json")
    requests = run.read("data_requests.json", [])
    cons = run.read("constraints.json", {"constraints": [], "stops": []})

    added = [_msg("human", "介入", text)]
    matched = False
    for rule in INTERVENTION_RULES:
        if not any(k in text for k in rule["any"]):
            continue
        if rule["neg"] and not any(n in text for n in rule["neg"]):
            continue
        matched = True
        if rule["constraint"] not in cons["constraints"]:
            cons["constraints"].append(rule["constraint"])
        if rule["stop_reason"]:
            cons["stops"].append({"item": rule["constraint"], "reason": rule["stop_reason"]})
        for nid, (status, reason) in rule["tree"].items():
            for n in tree["nodes"]:
                if n["id"] == nid:
                    n.update(status=status, reason=reason, source="介入")
        nr = rule["new_request"]
        if nr and not any(r["id"] == nr["id"] for r in requests):
            requests.append({**nr, "status": "請求中", "received": []})
        for who, msg, ruling in rule["responses"]:
            added.append(_msg(who, "介入後", msg, ruling=ruling))

    if not matched:
        # 事実の主張として扱えるかを、本物の形式審査にかける
        review = review_claim(Claim(speaker="human", text=text))
        added[0]["claim"] = {"text": text, "settle_condition": None}
        cons["constraints"].append(f"前提条件：{text}")
        added.append(_msg("judge", "形式審査",
                          f"介入を受理しました。形式審査の結果は「{review.verdict}」です（{review.reasons[0]}）。"
                          "事実の主張としては審理できないため、「前提条件」として登録します。"
                          "主張として審理を求める場合は、出典（書類と頁）と「何が観察されれば決着するか」を添えてください。",
                          ruling="登録"))

    run.write("debate_log.json", debate + added)
    run.write("decision_tree.json", tree)
    run.write("data_requests.json", requests)
    run.write("constraints.json", cons)
    refresh_derived(run)
    return added


# ---------------------------------------------------------------------------
# 追加資料の投入
# ---------------------------------------------------------------------------
DOC_TYPES = [
    # 上から順に判定する。財務諸表一式は、販管費などの個別の内訳より先に見る（「決算報告書」を販管費内訳と誤らない）
    ("借入金返済予定表", ["返済予定", "返済明細", "金銭消費貸借", "償還予定"]),
    ("勘定科目内訳明細書", ["内訳明細", "内訳書", "勘定科目"]),
    ("財務諸表（決算報告書）", ["決算報告書", "決算書", "財務諸表", "有価証券報告書", "有報", "計算書類",
                        "貸借対照表", "損益計算書", "FS", "fs", "securities-report"]),
    ("販管費内訳", ["販管費", "販売費", "一般管理費", "広告", "販促"]),
    ("品目別損益", ["品目", "製品別", "商品別", "粗利", "管理会計"]),
    ("工場別資料", ["工場", "稼働"]),
    ("人事資料", ["人事", "年齢", "人員"]),
    ("試算表", ["試算表"]),
    ("市況メモ", ["市況", "業界", "相場", "メモ"]),
]

FOLLOWUPS = {
    "販管費内訳": [
        ("growth", "これで価格転嫁と販促費の関係を検証できる。定番化で販促費を抑えたという説明（有報 p.24）が、数字で裏づけられるかを見よう。", None),
        ("rebuild", "TVCMの継続で広告宣伝費が増えているなら、増収の中身と合わせて費用対効果を問う。", None),
        ("judge", "争点「価格転嫁は機能している」の審理を再開します。決着条件は変わりません。数値の読み取りと検算が済むまで判定は保留します。", "再開"),
    ],
    "勘定科目内訳明細書": [
        ("radar", "数字の信用度の関門（CLAUDE.md 6.8）を再実行します。監視科目は仮払金・短期貸付金・役員借入金・保険積立金です。", None),
        ("rebuild", "売掛金の相手先別残高で、得意先の集中度を確かめたい。上位4社で売上の55%を占める（連結ベース、有報 p.23）。", None),
        ("judge", "争点「その他流動資産の中身」の審理を再開します。数値の読み取りと検算が済むまで判定は保留します。", "再開"),
    ],
    "品目別損益": [
        ("rebuild", "これで不採算品目を特定できる。決着条件どおり、粗利がマイナスの品目があるかを見る。", None),
        ("growth", "同時に、うるち主力品の粗利率が前期以上かも確かめる。私の主張の決着条件だ。", None),
        ("judge", "争点「不採算品目の即時整理」と「価格転嫁は機能している」の審理を再開します。数値の読み取りと検算が済むまで判定は保留します。", "再開"),
    ],
}


# 財務諸表一式には販管費の内訳（注記・内訳書）も含まれるので、販管費内訳のデータ請求も「受領」にする
DOC_COVERS = {"財務諸表（決算報告書）": {"財務諸表（決算報告書）", "販管費内訳"}}


def classify(filename: str) -> str:
    for doc_type, words in DOC_TYPES:
        if any(w in filename for w in words):
            return doc_type
    return "その他資料"


# データ請求と、それを解消する標準科目（値がそろえば「解消」）
REQUEST_KEYS = {"R1": ("sga_adv",), "R2": ("sga_promo",), "R4": ("suspense", "other_recv")}
# 会社ごとに番号が変わる自動の請求は、種類（kind）で解消の条件を持つ
KIND_KEYS = {"debt_schedule": ("cltd",)}

DEBT_REQUEST = {
    "kind": "debt_schedule", "item": "借入金返済予定表", "required": True, "by": "radar",
    "request_to": "金銭消費貸借契約書・借入金返済予定表（金融機関別の残高・毎月の返済額・最終返済期限）",
    "resolves": "約定返済額の確定（資金不足の有無＝トリアージに入るかどうかの判定の前提）",
    "doc_type": "借入金返済予定表",
}


def ensure_debt_request(run: Run) -> dict | None:
    """長期借入金などに1年内返済の区分がなく約定返済が確かめられないとき、Analyst Radar の必須の宿題として
    「借入金返済予定表」を自動で請求する（何度呼んでも一件だけ）。区分が確かめられるようになったら「解消」にする。"""
    import re

    if run.frozen:
        return None
    fin = run.financials()
    if fin is None:
        return None
    from core import repayment

    confirmed = repayment.load(run)
    base = metrics.cash_base(fin, confirmed)
    requests = run.read("data_requests.json", [])
    cur = next((r for r in requests if r.get("kind") == "debt_schedule"), None)
    if base.debt_unverified:
        if cur is not None and cur["status"] == "解消" and cur.get("resolved_how") == "人間が確定":
            cur["status"] = "請求中"   # 確定を取り消したら、宿題に戻す
            cur.pop("resolved_by", None)
            cur.pop("resolved_how", None)
            run.write("data_requests.json", requests)
            return cur
        if cur is None:
            n = max((int(r["id"][1:]) for r in requests if re.fullmatch(r"R\d+", r.get("id", ""))), default=0) + 1
            cur = {"id": f"R{n}", **DEBT_REQUEST, "status": "請求中", "received": [],
                   "note": metrics.debt_doubt_text(base) + "。" + metrics.reference_text(base)}
            run.write("data_requests.json", requests + [cur])
        return cur
    if cur is not None and cur["status"] != "解消":
        cur["status"] = "解消"
        if confirmed is not None:
            cur["resolved_how"] = "人間が確定"
            cur["resolved_by"] = [{"key": "repayment", "label": "年間約定返済額（人間が返済予定表で確定）",
                                   "cur": confirmed.amount, "source": {"file": confirmed.basis, "page": None}}]
        else:
            keys = KIND_KEYS["debt_schedule"]
            cur["resolved_how"] = "財務データ"
            cur["resolved_by"] = [{"key": k, "label": fin.items[k].label, "cur": fin.items[k].cur,
                                   "source": fin.items[k].source.model_dump()} for k in keys if k in fin.items]
        run.write("data_requests.json", requests)
    return cur


def _read_file(run: Run, saved_name: str, content: bytes, extractor):
    """tools.file_ingest で読み取り、結果を extracted/ に保存する。失敗しても資料の保存は取り消さない。"""
    from tools.file_ingest import ingest, merge_missing

    try:
        outcome = ingest(saved_name, content, company_id=run.company, extractor=extractor)
    except Exception as e:  # 読み取りの失敗は論争を止めない。理由を記録して人に返す
        run.write(f"extracted/{Path(saved_name).stem}.json", {"file": saved_name, "error": str(e), "at": now_iso()})
        return None, [], str(e)
    conflicts = []
    base = run.financials()
    if base is not None and not outcome.report.is_mock:
        _, conflicts = merge_missing(base, outcome.financials)
    run.write(f"extracted/{Path(saved_name).stem}.json", {
        "file": saved_name, "at": now_iso(), "extractor": outcome.report.extractor, "gate": outcome.gate,
        "summary": outcome.summary(), "report": outcome.report.model_dump(), "conflicts_with_existing": conflicts,
        "reconciliation": None if outcome.reconciliation is None else {
            "total": outcome.reconciliation.total, "一致": outcome.reconciliation.count("一致"),
            "不一致": outcome.reconciliation.count("不一致"), "未確認": outcome.reconciliation.count("未確認")},
        "financials": outcome.financials.model_dump(),
        "failed_checks": failed_checks(outcome),
        "materiality": outcome.materiality,
    })
    return outcome, conflicts, None


def failed_checks(outcome) -> list[dict]:
    """検算で一致しなかった項目（名前・期・計算値・報告値・差額・許容差）。"""
    if outcome is None or outcome.reconciliation is None:
        return []
    out = []
    for c in outcome.reconciliation.checks:
        if c.status != "不一致":
            continue
        for p in c.periods:
            if p.status == "不一致":
                out.append({"group": c.group, "name": c.name, "period": "前期" if p.period == "prev" else "当期",
                            "computed": p.computed, "reported": p.reported, "diff": p.diff, "tolerance": p.tolerance})
    return out


def adopt_financials(run: Run, outcome) -> str:
    """読み取った財務データを、その回次の財務データ（inputs/financials.json）として採用する。

    採用するのは、実際の読み取り（モックでない）で、財務諸表一式として検算ゲートを通過したものだけ。
    回次に自分の財務データがなければそのまま採用し、あれば欠けている科目だけを補う（既存の値は上書きしない）。
    戻り値：画面に出す一文（採用しなかった場合は空）。
    """
    from tools.file_ingest import merge_missing

    if outcome is None or outcome.report.is_mock or outcome.gate != "通過":
        return ""
    own = (run.path / "inputs" / "financials.json").exists()
    fin = outcome.financials
    if own:
        fin, _ = merge_missing(run.financials(), fin)
        run.write("inputs/financials.json", fin.model_dump())
        return "検算を通過したので、この回次の財務データに欠けている科目を補いました（既存の値は変えていません）。"
    run.write("inputs/financials.json", fin.model_dump())
    return "検算を通過したので、この回次の財務データとして採用しました。論争を始められます。"


def approve_rounding(run: Run, file: str) -> str:
    """条件付き適格（軽微な差異）の資料について、人の承認で差額を未解明差異として計上し、財務データとして採用する。

    監査証跡には「DDF条件付き適格を承認（未解明差異 N千円）」と残す。関数名は互換のため旧名のまま。
    """
    from core.guardrails import reconcile
    from core.materiality import adjustments, assess
    from schema import Financials

    run._guard()
    rec_path = f"extracted/{Path(file).stem}.json"
    x = run.read(rec_path)
    if not x or x.get("gate") != "軽微":
        raise ValueError("差異を承認して続行できるのは、条件付き適格（軽微な差異）と判定された資料だけです")
    fin = Financials.model_validate(x["financials"])
    m = assess(fin, reconcile(fin))
    if m is None or m.level != "軽微":
        raise ValueError("条件付き適格ではなくなりました（再判定の結果）")
    at = now_iso()
    fin.rounding_adjustments = fin.rounding_adjustments + adjustments(m, at, file)
    rec = reconcile(fin)
    if not rec.passed:
        raise ValueError("未解明差異を計上しても検算が一致しません")
    own = (run.path / "inputs" / "financials.json").exists()
    if own:
        from tools.file_ingest import merge_missing

        base = run.financials()
        merged, _ = merge_missing(base, fin)
        merged.rounding_adjustments = base.rounding_adjustments + fin.rounding_adjustments
        run.write("inputs/financials.json", merged.model_dump())
    else:
        run.write("inputs/financials.json", fin.model_dump())
    x["gate"] = "通過（端数調整）"
    x["approved_at"] = at
    x["financials"] = fin.model_dump()
    run.write(rec_path, x)
    lines = [f"{a.check}（{'当期' if a.period == 'cur' else '前期'}）{a.amount:+,} → {a.booked_to}" for a in fin.rounding_adjustments]
    entry = {"at": at, "actor": "人間（ライム）", "action": f"DDF条件付き適格を承認（未解明差異 {m.total_diff_thousand:,.0f}千円）",
             "file": file,
             "total_diff_thousand": m.total_diff_thousand, "headline": m.headline(), "entries": lines}
    run.write("audit_log.json", run.read("audit_log.json", []) + [entry])
    run.write("debate_log.json", run.read("debate_log.json", []) + [
        _msg("human", "承認", f"DDF条件付き適格を承認：未解明差異（{m.total_diff_thousand:,.0f}千円）の計上：{file}"),
        _msg("judge", "検算ゲート", f"未解明差異（DM未満・承認済み）を計上し、検算が全項目で一致しました（{m.headline()}）。"
                                    "書類に書かれた合計を正として、この回次の財務データに採用します。", ruling="登録"),
    ])
    return f"未解明差異（{m.total_diff_thousand:,.0f}千円）を計上して採用しました（DDF：条件付き適格）。監査証跡に記録しています。"


def choose_replace(run: Run, file: str) -> str:
    """軽微な差異の資料を採用せず、訂正した資料の差し替えを待つ。"""
    rec_path = f"extracted/{Path(file).stem}.json"
    x = run.read(rec_path)
    if not x or x.get("gate") != "軽微":
        return ""
    x["gate"] = "差し替え待ち"
    run.write(rec_path, x)
    run.write("audit_log.json", run.read("audit_log.json", []) + [
        {"at": now_iso(), "actor": "人間（ライム）", "action": "財務諸表の差し替えを選択（未解明差異は承認しない）", "file": file}])
    return "この資料は採用しません。訂正した財務諸表を投入してください。"


WITHDRAWN_DIR = "withdrawn"


def withdrawable(run: Run, path: Path | None) -> tuple[bool, str]:
    """投入済みの資料を取り下げられるか。戻り値：（可否、できない理由または空）。

    取り下げられるのは、開いている回次に人が投入したファイルだけ。同梱の見本（titles.json に表示名があるもの）、
    親の回次から引き継いだもの、数値がこの回次の財務データに採用されているものは取り下げない。
    """
    import json

    if path is None:
        return False, "読み取った数値の出典書類で、ファイルとしては保存していません"
    if run.frozen:
        return False, "凍結済みの回次の資料は取り下げられません"
    inputs = run.path / "inputs"
    if path.parent.resolve() != inputs.resolve() or path.name == "financials.json":
        return False, "親の回次から引き継いだ資料です。取り下げは、その資料を投入した回次でしか行えません"
    try:
        titles = json.loads((inputs / "titles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        titles = {}
    if path.name in titles:
        return False, "同梱の見本資料です"
    own = inputs / "financials.json"
    if own.exists():
        fin = run.financials()
        if fin is not None and any(it.source.file == path.name for it in fin.items.values()):
            return False, ("この資料の数値はこの回次の財務データに採用済みです。取り下げると論争の前提が崩れるため、"
                           "訂正した資料は新しい分析回次に投入してください")
    return True, ""


def withdraw_input(run: Run, filename: str) -> str:
    """投入済みの資料を取り下げる。消さずに withdrawn/ へ移し、読み取り記録・データ請求・監査証跡を整える。"""
    run._guard()
    path = run.path / "inputs" / Path(filename).name
    if not path.exists():
        raise ValueError(f"資料「{filename}」が見つかりません")
    ok, why = withdrawable(run, path)
    if not ok:
        raise ValueError(why)
    at = now_iso()
    trash = run.path / WITHDRAWN_DIR
    trash.mkdir(parents=True, exist_ok=True)
    stamp_ = at.replace(":", "").replace("-", "")
    path.rename(trash / f"{stamp_}_{path.name}")
    rec = run.path / "extracted" / f"{path.stem}.json"
    if rec.exists():
        rec.rename(trash / f"{stamp_}_{path.stem}.extracted.json")

    reverted = []
    requests = run.read("data_requests.json", [])
    for r in requests:
        received = [x for x in r.get("received", []) if not (x.get("file") == path.name and x.get("run") == run.run_id)]
        from_this = any((v.get("source") or {}).get("file") == path.name for v in r.get("resolved_by", []))
        changed = len(received) != len(r.get("received", [])) or from_this
        if not changed:
            continue
        r["received"] = received
        if from_this:
            r.pop("resolved_by", None)
        if from_this or (r["status"] == "受領（検証待ち）" and not received):
            r["status"] = "受領（検証待ち）" if received else "請求中"
            reverted.append(r["id"])
    if requests:
        run.write("data_requests.json", requests)

    title = path.stem
    run.write("audit_log.json", run.read("audit_log.json", []) + [
        {"at": at, "actor": "人間（ライム）", "action": "投入資料の取り下げ", "file": path.name,
         "entries": [f"保管先：{WITHDRAWN_DIR}/{stamp_}_{path.name}（削除せず保管）"]
                    + ([f"データ請求 {'・'.join(reverted)} の受領を取り消し"] if reverted else [])}])
    run.write("debate_log.json", run.read("debate_log.json", []) + [
        _msg("human", "資料取り下げ", f"投入資料を取り下げ：{path.name}（以後は引用できない。これまでの発言の記録は残す）")])
    refresh_derived(run)
    return f"「{title}」を取り下げました（削除せず保管し、監査証跡に記録しています）"


def opens_new_run(company: str) -> bool:
    """財務書類を投入したとき、新しい回次を開くか（handle_upload と同じ規則）。"""
    run = latest_run(company)
    empty_first = run.meta.seq == 1 and not run.frozen and run.financials_source() is None
    return (run.meta.seq == 1 and not empty_first) or run.frozen


def handle_upload(company: str, filename: str, content: bytes, extractor=None) -> tuple[Run, list[dict], bool]:
    """追加資料を最新の回次に保存し、読み取り（tools.file_ingest）と検算ゲートにかけ、データ請求の解消イベントとして処理する。

    最新が第1次分析なら、第1次を凍結して第2次分析を開く。第2次以降で開いていれば、そこに追加する。
    戻り値：（保存先の回次、追加メッセージ、新しい回次を開いたか）
    """
    run = latest_run(company)
    opened = False
    if opens_new_run(company):   # 財務データのない第1次分析には、そのまま格納する
        run = start_next_run(company, trigger=f"追加資料の投入：{filename}")
        opened = True
        prev = run.parent()
        run.write("debate_log.json", [
            _msg("judge", "引き継ぎ",
                 f"{prev.meta.label}を凍結し、{run.meta.label}を開きます。前回の暫定整理、制約、未解決のデータ請求を引き継ぎます。",
                 ruling="登録"),
        ])

    saved = run.save_input(filename, content)
    outcome, conflicts, error = _read_file(run, saved.name, content, extractor)
    real = outcome is not None and not outcome.report.is_mock
    adopted = adopt_financials(run, outcome)

    doc_type = classify(filename)
    if doc_type == "その他資料" and real:
        doc_type = classify(outcome.report.document_type)

    requests = run.read("data_requests.json", [])
    touched, resolved = [], []
    for r in requests:
        if r.get("doc_type") in DOC_COVERS.get(doc_type, {doc_type}) and r["status"] in ("請求中", "受領（検証待ち）"):
            r["status"] = "受領（検証待ち）"
            r.setdefault("received", []).append({"file": saved.name, "run": run.run_id, "at": now_iso()})
            touched.append(r)
    if real and outcome.gate not in ("停止", "未確認"):
        items = outcome.financials.items
        for r in requests:
            keys = REQUEST_KEYS.get(r["id"]) or KIND_KEYS.get(r.get("kind", ""))
            if keys and r["status"] != "解消" and all(k in items and items[k].cur is not None for k in keys):
                r["status"] = "解消"
                r["resolved_by"] = [{"key": k, "label": items[k].label, "cur": items[k].cur,
                                     "source": items[k].source.model_dump()} for k in keys]
                resolved.append(r)

    size_kb = max(1, round(len(content) / 1024))
    head = f"追加資料「{saved.name}」（{size_kb}KB）を受領しました。資料の種別を「{doc_type}」と判定しました。"
    if error:
        body = f"読み取りに失敗しました（{error}）。資料は保存済みです。数値は未確認のまま扱います。"
    elif outcome.report.is_mock:
        body = (f"読み取りエンジン：モック（{config.mock_reason()}）。ファイルの中身は読まず、制作サンプル（C001 アルファ製菓・モデル企業 第73期）を返しています。"
                + outcome.summary() + "。")
    else:
        body = f"読み取りエンジン：{outcome.report.extractor}。{outcome.summary()}。"
        if outcome.report.remapped:
            body += f"別名を標準科目に吸収したもの{len(outcome.report.remapped)}件。"
        if conflicts:
            body += f"既存の数値と食い違うもの{len(conflicts)}件（上書きせず記録）。"
    if touched:
        body += "データ請求 " + "、".join(f"{r['id']} {r['item']}" for r in touched) + " を「受領（検証待ち）」に更新しました。"
    for r in resolved:
        vals = "、".join(f"{v['label']} {v['cur']:,}（{v['source']['file']} p.{v['source']['page'] or '？'}）" for v in r["resolved_by"])
        body += f"{r['id']} {r['item']} は数値を取得したため「解消」としました：{vals}。"

    if adopted:
        body += adopted
    added = [_msg("human", "資料投入", f"追加資料を投入：{saved.name}"),
             _msg("radar", "資料受領", head + body, [{"file": saved.name, "page": None}])]
    if outcome is not None and outcome.gate == "停止":
        m = outcome.materiality or {}
        head = m.get("headline", "")
        qual = "".join(f"質的重要性に抵触：{q}。" for q in m.get("qualitative") or [])
        added.append(_msg("judge", "検算ゲート",
                          f"診断適格性（DDF）：不適格。重大な計算不一致（{head}）のため、診断プロセスを停止しました。{qual}"
                          "誤ったトリアージ判定を防ぐため、この資料の数値は論争に使いません。元資料の数値を訂正のうえ再投入してください。",
                          ruling="保留"))
    elif outcome is not None and outcome.gate == "未確認":
        core = "・".join((outcome.materiality or {}).get("unverified_core", []))
        added.append(_msg("judge", "検算ゲート",
                          f"診断適格性（DDF）：不適格。中心となる検算（{core}）を確かめられないため、診断プロセスを停止しました。"
                          "確かめていない数値で論争を始めることはしません。読み取れなかった行を確かめ、資料を補って再投入してください。",
                          ruling="保留"))
    elif outcome is not None and outcome.gate == "軽微":
        head = (outcome.materiality or {}).get("headline", "")
        added.append(_msg("judge", "検算ゲート",
                          f"診断適格性（DDF）：条件付き適格。軽微な計算差異（{head}）は診断重要性（DM）の範囲内で、"
                          "質的重要性（赤字転落・債務超過・資金不足の有無）への抵触はありません。財務諸表を差し替えるか、"
                          "差異を承認して続行するかを人が選ぶまで、この資料の数値は論争に使いません。", ruling="保留"))
    elif touched:
        added += [_msg(w, "新事実", t, ruling=rl) for w, t, rl in FOLLOWUPS.get(doc_type, [])]
    else:
        added.append(_msg("judge", "新事実", "関連するデータ請求はありません。論点にするかどうかは、提出者の説明（出典と決着条件）を待ちます。",
                          ruling="保留"))

    if doc_type == "品目別損益":
        tree = run.read("decision_tree.json")
        for n in tree["nodes"]:
            if n["id"] == "C2" and n["status"] == "保留":
                n["reason"] = f"品目別損益を受領（{saved.name}、検証待ち）"
        run.write("decision_tree.json", tree)

    run.write("debate_log.json", run.read("debate_log.json", []) + added)
    run.write("data_requests.json", requests)
    refresh_derived(run)
    return run, added, opened


# ---------------------------------------------------------------------------
# 差分とレポート
# ---------------------------------------------------------------------------
def diff_from_parent(run: Run) -> dict | None:
    parent = run.parent()
    if parent is None:
        return None
    before = {r["id"]: r for r in parent.read("data_requests.json", [])}
    after = run.read("data_requests.json", [])
    changed = [(r, before[r["id"]]["status"]) for r in after if r["id"] in before and before[r["id"]]["status"] != r["status"]]
    new = [r for r in after if r["id"] not in before]
    pc = set(parent.read("constraints.json", {}).get("constraints", []))
    rc = run.read("constraints.json", {}).get("constraints", [])
    open_left = [r for r in after if r["status"] == "請求中"]
    return {
        "parent_label": parent.meta.label,
        "inputs": [input_title(p) + p.suffix for p in run.inputs()],
        "changed_requests": [{"id": r["id"], "item": r["item"], "from": s, "to": r["status"]} for r, s in changed],
        "new_requests": [{"id": r["id"], "item": r["item"]} for r in new],
        "new_constraints": [c for c in rc if c not in pc],
        "open_requests": [{"id": r["id"], "item": r["item"]} for r in open_left],
        "messages": len(run.read("debate_log.json", [])),
    }


def diff_markdown(d: dict) -> str:
    lines = [f"# 前回（{d['parent_label']}）からの差分", ""]
    lines.append("## 追加投入資料")
    lines += [f"- {n}" for n in d["inputs"]] or ["- なし"]
    lines += ["", "## 宿題（データ請求）の状況の変化"]
    lines += [f"- {c['id']} {c['item']}：{c['from']} → {c['to']}" for c in d["changed_requests"]] or ["- 変化なし"]
    if d["new_requests"]:
        lines += ["", "## 新たなデータ請求"] + [f"- {r['id']} {r['item']}" for r in d["new_requests"]]
    if d["new_constraints"]:
        lines += ["", "## 新たな制約・前提条件"] + [f"- {c}" for c in d["new_constraints"]]
    lines += ["", "## 未解決のデータ請求"]
    lines += [f"- {r['id']} {r['item']}" for r in d["open_requests"]] or ["- なし"]
    return "\n".join(lines) + "\n"


def report_markdown(run: Run) -> str:
    meta = run.meta
    fin = run.financials()
    rep = reconcile(fin) if fin else None
    tree = run.read("decision_tree.json", {"nodes": []})
    requests = run.read("data_requests.json", [])
    cons = run.read("constraints.json", {"constraints": [], "stops": []})
    from core.ddf import run_status

    L = [f"# 経営診断レポート　{meta.label}（{meta.as_of}）", "",
         f"**財務データ診断適格性：{run_status(run)}**", "",
         f"- 状態：{'凍結済み' if meta.status == 'frozen' else '作業中'}　作成：{meta.created_at}",
         f"- 対象：{fin.fiscal_period if fin else '—'}　{fin.basis if fin else ''}", ""]
    if rep:
        L += ["## 検算ゲート", f"- 全{rep.total}項目　一致{rep.count('一致')}　不一致{rep.count('不一致')}　未確認{rep.count('未確認')}"
              f"（端数差{rep.rounding_diffs}件は許容差内）", ""]
    L += ["## シナリオの採否"]
    for n in tree["nodes"]:
        L.append(f"- {n['id']} {n['label']}：{n['status']}　— {n['reason']}（{n['source']}）")
    L += ["", "## データ請求（宿題リスト）"]
    for r in requests:
        must = "【必須】" if r.get("required") else ""
        L.append(f"- {r['id']} {must}{r['item']}：{r['status']}　請求先：{r['request_to']}　解消する争点：{r['resolves']}")
    from core import repayment

    rp = repayment.load(run)
    if rp is not None:
        L += ["", "## 約定返済（人間が確定）", f"- {rp.describe()}　確定日時：{rp.at}（資金の監視はこの額で計算。決算書の数字は変えていない）"]
    L += ["", "## 制約・前提条件"]
    L += [f"- {c}" for c in cons["constraints"]] or ["- なし"]
    return "\n".join(L) + "\n"


def refresh_derived(run: Run) -> None:
    """開いている回次の派生ファイル（差分・レポート）を更新する。凍結済みなら何もしない。"""
    if run.frozen:
        return
    ensure_debt_request(run)
    d = diff_from_parent(run)
    if d is not None:
        run.write_text("diff_summary.md", diff_markdown(d))
    run.write_text(f"report_v{run.meta.seq}.md", report_markdown(run))


def start_manual_run(company: str) -> Run:
    run = start_next_run(company, trigger="操作者が新しい分析回次を開始")
    prev = run.parent()
    run.write("debate_log.json", [
        _msg("judge", "引き継ぎ",
             f"{prev.meta.label}を凍結し、{run.meta.label}を開きます。前回の暫定整理、制約、未解決のデータ請求を引き継ぎます。",
             ruling="登録")])
    refresh_derived(run)
    return run


__all__ = ["apply_intervention", "handle_upload", "diff_from_parent", "report_markdown", "review_message",
           "seed_initial_run", "start_manual_run", "list_runs", "latest_run"]
