"""検算ゲートの二段階判定（重要性 0.5%・100万円）と、人が承認する端数調整。本物の Gemini は呼ばない。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core import materiality as mt
from core.guardrails import reconcile
from core.mock_engine import approve_rounding, choose_replace, handle_upload
from core.runs import create_company, latest_run
from schema import Financials
from tools.file_ingest import MockExtractor

ROOT = Path(__file__).resolve().parents[1]
CRISIS = ROOT / "data/companies/C002_sample_crisis/runs/run_001_initial/inputs/financials.json"


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _fin(**shift) -> Financials:
    fin = Financials.model_validate(json.loads(CRISIS.read_text(encoding="utf-8")))
    for key, d in shift.items():
        fin.items[key].cur += d
    return fin


class Shifted(MockExtractor):
    """C002 の検算済みデータの一部をずらして返す（実際の読み取りに見せかける）。"""

    name = "gemini:fake"

    def __init__(self, **shift):
        super().__init__(CRISIS)
        self.shift = shift

    def extract(self, filename, content):
        ex = super().extract(filename, content)
        for it in ex.items:
            if it.key in self.shift:
                it.cur += self.shift[it.key]
        return ex


def test_clean_statements_have_no_materiality():
    assert mt.assess(_fin(), reconcile(_fin())) is None


def test_small_difference_is_minor():
    fin = _fin(oca=300)                                   # 流動資産の内訳だけ 300千円ずれる
    m = mt.assess(fin, reconcile(fin))
    assert m.level == "軽微" and m.total_diff == 300 and m.pct_assets < 0.005
    assert m.headline() == f"差額: 300千円、総資産の{300 / 890_500:.3%}"


@pytest.mark.parametrize("shift,reason", [
    ({"oca": 1_000}, "100万円以上"),                     # 金額の上限ちょうど
    ({"oca": 5_000}, "総資産の"),                        # 0.5% 以上（890,500 × 0.5% ≒ 4,452）
])
def test_large_difference_is_major(shift, reason):
    fin = _fin(**shift)
    m = mt.assess(fin, reconcile(fin))
    assert m.level == "重大" and any(reason in r for r in m.reasons)


def test_missing_base_is_major():
    fin = _fin(oca=300)
    fin.items["sales"].cur = None
    fin.items["sales"].prev = None
    assert mt.assess(fin, reconcile(fin)).level == "重大"


def test_booking_rules():
    F = mt.Failure
    assert mt.booked_to(F("BS内訳", "流動資産合計", "cur", 1, 2, -1)) == "その他流動資産（端数調整差額）"
    assert mt.booked_to(F("BS内訳", "流動負債合計", "cur", 1, 2, -1)) == "その他流動負債（端数調整差額）"
    assert mt.booked_to(F("貸借一致", "資産合計＝負債純資産合計", "cur", 99, 100, -1)) == "その他流動資産（端数調整差額）"
    assert mt.booked_to(F("貸借一致", "資産合計＝負債純資産合計", "cur", 101, 100, 1)) == "その他流動負債（端数調整差額）"
    assert mt.booked_to(F("段階利益", "営業利益", "cur", 1, 2, -1)) == "雑損益（端数調整）"


def test_minor_upload_waits_for_a_human_then_adjusts(data):
    company = create_company("端数商事", "製造業", fictional=True)
    run, added, opened = handle_upload(company, "決算書_第62期.pdf", b"%PDF", Shifted(oca=300))
    assert not opened and run.financials() is None                        # 人が選ぶまで採用しない
    x = run.read("extracted/決算書_第62期.json")
    assert x["gate"] == "軽微" and x["materiality"]["level"] == "軽微"
    assert "軽微な計算差異" in added[-1]["text"]
    msg = approve_rounding(run, "決算書_第62期.pdf")
    assert "300千円" in msg
    fin = run.financials()
    rec = reconcile(fin)
    assert rec.passed and rec.adjusted_count == 1
    adj = fin.rounding_adjustments[0]
    assert adj.check == "流動資産合計" and adj.amount == -300 and adj.booked_to.startswith("その他流動資産")
    assert fin.value("ta") == 890_500                                      # 書類の合計は正として残す
    log = run.read("audit_log.json")
    assert log[-1]["action"] == "端数調整差額の計上を承認" and log[-1]["total_diff_thousand"] == 300
    assert run.read("extracted/決算書_第62期.json")["gate"] == "通過（端数調整）"
    with pytest.raises(ValueError):
        approve_rounding(run, "決算書_第62期.pdf")                          # 二度は承認できない


def test_minor_upload_can_be_replaced_instead(data):
    company = create_company("差替工業", "製造業", fictional=True)
    run, _, _ = handle_upload(company, "決算書.pdf", b"%PDF", Shifted(oca=300))
    assert "訂正した財務諸表" in choose_replace(run, "決算書.pdf")
    assert run.financials() is None and run.read("extracted/決算書.json")["gate"] == "差し替え待ち"
    assert run.read("audit_log.json")[-1]["action"].startswith("財務諸表の差し替え")


def test_major_upload_is_blocked(data):
    company = create_company("重大製作所", "製造業", fictional=True)
    run, added, _ = handle_upload(company, "決算書.pdf", b"%PDF", Shifted(oca=5_000))
    assert run.financials() is None and run.read("extracted/決算書.json")["gate"] == "停止"
    assert "重大な計算不一致" in added[-1]["text"] and "再投入" in added[-1]["text"]
    with pytest.raises(ValueError):
        approve_rounding(run, "決算書.pdf")


def test_headline_lists_the_parts_when_several_checks_differ():
    from core.materiality import Failure, Materiality

    fs = [Failure("段階利益", "販管費合計", "cur", 70_657, 73_657, -3_000),
          Failure("原価の流れ", "売上原価（調整表）", "cur", 252_120, 275_751, -23_631)]
    m = Materiality("重大", 26_631, 26_631.0, 26_631 / 424_948, 26_631 / 322_243, fs, [])
    assert m.headline() == ("差額合計: 26,631千円（2件：売上原価（調整表） 23,631・販管費合計 3,000）、"
                            f"総資産の{26_631 / 424_948:.3%}")
    many = fs + [Failure("BS内訳", "流動資産合計", "prev", 1, 2, -1), Failure("BS内訳", "負債合計", "cur", 5, 7, -2)]
    m2 = Materiality("重大", 26_634, 26_634.0, 0.1, 0.1, many, [])
    assert "4件：" in m2.headline() and "ほか1件" in m2.headline() and "流動資産合計（前期）" not in m2.headline()


def test_old_gate_records_get_the_new_headline():
    from core.digest import gate_headline

    rec = {"materiality": {"headline": "差額: 26,631千円、総資産の6.267%", "total_diff_thousand": 26631.0,
                           "pct_assets": 26_631 / 424_948},
           "failed_checks": [{"name": "販管費合計", "period": "当期", "diff": -3000},
                             {"name": "売上原価（調整表）", "period": "当期", "diff": -23631}],
           "financials": {"unit": "千円"}}
    assert gate_headline(rec).startswith("差額合計: 26,631千円（2件：売上原価（調整表） 23,631・販管費合計 3,000）")
    rec["failed_checks"] = rec["failed_checks"][:1]
    assert gate_headline(rec) == "差額: 26,631千円、総資産の6.267%"                    # 1件ならそのまま
