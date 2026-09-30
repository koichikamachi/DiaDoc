"""約定返済が書類から確かめられないとき（長期借入金に1年内返済の区分がない）の扱い（2026-09-30、乙精機ケースBの臨床テストから）。

返済を0とみなすと「資金不足なし」に見えるが、行がない＝返済がない、ではない。資金不足の有無は判定保留にし、
トリアージ不要と言い切らない。返済予定表を必須の宿題として請求し、参考試算（10年均等返済）を並べる。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core import metrics
from core.guardrails import DEFAULT_POLICY, decide_phase
from core.metrics import cash_base, project, reference_text, runway_label
from core.mock_engine import ensure_debt_request, handle_upload, report_markdown
from core.runs import create_company
from test_ddf import _Fixed, _lines
from tools.file_ingest import normalize

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _fin(ordinary=8_700, ltd=100_000, cltd=None):
    """乙精機ケースBの資金の姿：経常利益8,700・法人税等70・減価償却費なし・現金20,000・長期借入金100,000（区分なし）。"""
    fin = normalize(_Fixed(_lines(sga_reported=49_800)).ex, "乙.xlsx", "C9", "g")[0]
    fin.items["ord"].cur = ordinary
    fin.items["cash"].cur = 20_000
    fin.items["ltd"].cur = ltd
    if cltd is not None:
        fin.items["cltd"] = fin.items["ltd"].model_copy(update={"key": "cltd", "label": "1年内返済予定の長期借入金",
                                                               "cur": cltd})
    return fin


def test_missing_current_portion_is_not_read_as_no_repayment():
    b = cash_base(_fin())
    assert b.free_cf == 8_630 and b.required_cf == 0            # 返済を0とした値（従来の見え方）
    assert b.debt_unverified == ["長期借入金 100,000千円に1年内返済の区分がない"]
    assert b.shortage_pending
    assert (b.ref_debt_service, b.ref_free_cf) == (10_000, -1_370)
    assert reference_text(b) == "参考試算（例：10年均等返済なら年10,000千円、返済後CF △1,370千円）"
    assert metrics.debt_doubt_text(b).startswith("約定返済：BS記載に疑問あり、確認が必要")
    assert any("BS記載に疑問あり、確認が必要" in x for x in b.basis)


def test_stated_current_portion_is_trusted():
    b = cash_base(_fin(cltd=10_000))
    assert not b.debt_unverified and not b.shortage_pending and b.free_cf == -1_370 and b.required_cf == 1_370


def test_shortage_is_certain_even_with_zero_repayment():
    """返済を0とみなしても不足なら、返済を入れれば不足はさらに大きい。不足は確かなので判定保留にしない。"""
    b = cash_base(_fin(ordinary=-5_000))
    assert b.debt_unverified and not b.shortage_pending and b.required_cf > 0


def test_runway_is_not_called_no_outflow_while_pending():
    assert runway_label(None, 8_630, pending=True) == "判定保留（約定返済が未確認）"
    assert runway_label(None, 8_630, short=True, pending=True) == "判定保留"
    assert runway_label(None, 8_630) == "資金流出なし"


@pytest.mark.parametrize("stalemate,rounds,rule", [(DEFAULT_POLICY.stalemate_limit, 1, "stalemate_pending"),
                                                   (0, DEFAULT_POLICY.max_rounds, "max_rounds_pending")])
def test_debate_closes_as_pending_not_as_no_triage(stalemate, rounds, rule):
    m = project(cash_base(_fin()), [], stalemate, rounds)
    d = decide_phase("exploration", m)
    assert d.next == "settlement" and d.rule == rule
    assert d.stop_reason == "判定保留（返済予定表の開示待ち）"
    assert "トリアージ不要とは確定しません" in d.reason and "△1,370" in d.reason


def test_debate_continues_normally_before_the_limit():
    d = decide_phase("exploration", project(cash_base(_fin()), [], 0, 1))
    assert d.next == "exploration" and "必要CF 判定保留（返済予定表の開示待ち）" in d.reason


def test_repayment_schedule_is_requested_once_as_radars_required_homework(data):
    company = create_company("丁工業", fictional=True)
    run, _, _ = handle_upload(company, "丁.xlsx", b"x", extractor=_Fixed(_lines(sga_reported=49_800)))
    reqs = [r for r in run.read("data_requests.json", []) if r.get("kind") == "debt_schedule"]
    assert len(reqs) == 1
    r = reqs[0]
    assert r["item"] == "借入金返済予定表" and r["required"] and r["by"] == "radar" and r["status"] == "請求中"
    assert "金銭消費貸借契約書" in r["request_to"] and "参考試算" in r["note"]
    ensure_debt_request(run)
    ensure_debt_request(run)
    assert len([x for x in run.read("data_requests.json") if x.get("kind") == "debt_schedule"]) == 1
    assert "【必須】借入金返済予定表" in report_markdown(run)


def test_request_is_resolved_when_the_current_portion_becomes_known(data):
    company = create_company("丁工業", fictional=True)
    run, _, _ = handle_upload(company, "丁.xlsx", b"x", extractor=_Fixed(_lines(sga_reported=49_800)))
    fin = run.financials()
    fin.items["cltd"] = fin.items["ltd"].model_copy(update={"key": "cltd", "label": "1年内返済予定の長期借入金", "cur": 6_000})
    run.write("inputs/financials.json", fin.model_dump())
    r = ensure_debt_request(run)
    assert r["status"] == "解消" and r["resolved_by"][0]["cur"] == 6_000


def test_samples_are_unaffected():
    from core.runs import latest_run

    for c in ("C001_sample_alpha", "C002_sample_crisis"):
        assert not cash_base(latest_run(c).financials()).debt_unverified


# ---------------------------------------------------------------------------
# 審判の総括：継続改善CF（ラン）と一括調達（ショット）を分けて並べる
# ---------------------------------------------------------------------------
def _note(base, bridges):
    from core.graph import judge_note, judge_text
    from state import DebateState

    m = project(base, bridges, 0, 1)
    st = DebateState(company_id="C", run_id="r", monitor=m)
    note = judge_note([], decide_phase("exploration", m), "", st, m)
    return note, judge_text(note, st)


def test_one_time_cash_is_shown_separately_from_recurring_improvement():
    from schema import CausalBridge

    sale = CausalBridge(account="inv", direction="減", amount=500, cf_effect=500, lead_months=1, recurring=False)
    note, text = _note(cash_base(_fin()), [("R1-growth-3", sale)])
    assert note.one_time == 500 and note.accumulated == 0
    assert "一括調達（一時的資金）：500千円" in text
    assert "継続改善CF（回収CF累計・年）0千円" in text


def test_judge_summary_states_the_pending_judgement():
    note, text = _note(cash_base(_fin()), [])
    assert note.pending.startswith("約定返済：BS記載に疑問あり、確認が必要")
    assert "必要CF 判定保留（返済予定表の開示待ち）" in text and "資金流出なし" not in text
    assert "参考試算（例：10年均等返済なら年10,000千円、返済後CF △1,370千円）" in text
    note2, text2 = _note(cash_base(_fin(cltd=10_000)), [])
    assert not note2.pending and "判定保留" not in text2


def test_cockpit_shows_pending_instead_of_no_outflow(data):
    """画面：右ペインの残余月数、ボトルネック、1ラウンド後の裁定カードが「判定保留」と参考試算を出す。"""
    from streamlit.testing.v1 import AppTest

    from core.graph import DebateSession
    from core.runs import latest_run

    company = create_company("丁工業", fictional=True)
    handle_upload(company, "丁.xlsx", b"x", extractor=_Fixed(_lines(sga_reported=49_800)))
    DebateSession(latest_run(company)).run_round()
    at = AppTest.from_file(str(ROOT / "src/ui/app.py"), default_timeout=30)
    at.run()
    at.selectbox(key="company").set_value(company).run()
    assert not at.exception, at.exception
    html_ = " ".join(str(h.proto.body) for h in at.get("html")) + " ".join(m.value for m in at.markdown)
    assert "判定保留" in html_ and "△5,370" in html_ and "一括調達（一時的資金）" in html_
    assert "返済後の資金収支はプラスで、資金の不足はない" not in html_
