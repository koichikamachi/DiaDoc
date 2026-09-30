"""診断適格性（DDF）：適格／条件付き適格／不適格と、質的重要性（金額が小さくても診断の結論を変える差）。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core import ddf
from core.materiality import Failure
from core.mock_engine import approve_rounding, handle_upload, report_markdown
from core.runs import create_company
from tools.file_ingest import Extraction, ExtractedItem, ingest, normalize

ROOT = Path(__file__).resolve().parents[1]
BS, PL = "貸借対照表", "損益計算書"


def _lines(sga_reported=50_100, sga_detail=(30_000, 19_800), gp=50_000):
    """小さな架空会社（丁工業）。販管費の記載額と内訳の合計に差を作れる。営業利益は記載額から出す（書類どおり）。"""
    op = gp - sga_reported
    ordi = op + 500
    ni = ordi - 70
    return [
        ("cash", "現金及び預金", 20_000, BS), ("ar", "売掛金", 10_000, BS), ("tca", "流動資産合計", 30_000, BS),
        ("land", "土地", 70_000, BS), ("tppe", "有形固定資産合計", 70_000, BS), ("tfa", "固定資産合計", 70_000, BS),
        ("ta", "資産合計", 100_000, BS), ("ap", "買掛金", 5_000, BS), ("tcl", "流動負債合計", 5_000, BS),
        ("ltd", "長期借入金", 60_000, BS), ("tltl", "固定負債合計", 60_000, BS), ("tl", "負債合計", 65_000, BS),
        ("cs", "資本金", 10_000, BS), ("re", "繰越利益剰余金", 25_000, BS), ("tsh", "株主資本合計", 35_000, BS),
        ("tna", "純資産合計", 35_000, BS), ("tle", "負債純資産合計", 100_000, BS),
        ("sales", "売上高", 200_000, PL), ("cogs", "売上原価", 200_000 - gp, PL), ("lab", "労務費", 50_000, PL),
        ("exp", "経費", 150_000 - gp, PL), ("gp", "売上総利益", gp, PL), ("sga", "販売費及び一般管理費", sga_reported, PL),
        ("sga_officer", "役員報酬", sga_detail[0], PL), ("sga_salary", "給料手当", sga_detail[1], PL),
        ("op", "営業利益", op, PL), ("ii", "受取利息", 500, PL), ("tnoi", "営業外収益合計", 500, PL),
        ("tnoe", "営業外費用合計", 0, PL), ("ord", "経常利益", ordi, PL), ("pbt", "税引前当期純利益", ordi, PL),
        ("ctx", "法人税、住民税及び事業税", 70, PL), ("ni", "当期純利益", ni, PL),
    ]


class _Fixed:
    name = "gemini:fake"

    def __init__(self, lines):
        self.ex = Extraction(document_type="財務諸表", fiscal_period="第5期", unit="千円",
                             items=[ExtractedItem(key=k, source_label=lab, cur=v, page=sec, section=sec)
                                    for k, lab, v, sec in lines])

    def extract(self, filename, content):
        return self.ex


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_consistent_statement_is_fit(data):
    company = create_company("丁工業", fictional=True)
    run, _, _ = handle_upload(company, "丁.xlsx", b"x", extractor=_Fixed(_lines(sga_reported=49_800)))
    assert run.read("extracted/丁.json")["gate"] == "通過" and ddf.run_status(run) == ddf.FIT
    assert "- **診断適格性（DDF）**：適格（Fit）" in report_markdown(run)


def test_small_difference_is_conditionally_fit_and_needs_a_human(data):
    """販管費の記載額が内訳より300千円多い。営業利益は黒字のまま（10,000 → 10,300）なので質的には問題ない。"""
    company = create_company("丁工業", fictional=True)
    lines = _lines(sga_reported=40_100, sga_detail=(30_000, 9_800))
    run, added, _ = handle_upload(company, "丁.xlsx", b"x", extractor=_Fixed(lines))
    x = run.read("extracted/丁.json")
    assert x["gate"] == "軽微" and x["materiality"]["qualitative"] == []
    assert ddf.gate_label(x["gate"]) == "条件付き適格（Conditionally Fit）：承認待ち"
    assert "条件付き適格" in added[-1]["text"] and run.financials() is None
    approve_rounding(run, "丁.xlsx")
    log = run.read("audit_log.json")[-1]
    assert f"{log['actor']}：{log['action']}" == "人間（ライム）：DDF条件付き適格を承認（未解明差異 300千円）"
    assert run.financials().rounding_adjustments[0].booked_to == "雑損益（未解明差異）"
    assert "- **診断適格性（DDF）**：条件付き適格（Conditionally Fit）：未解明差異 300千円を承認済み" in report_markdown(run)


def test_small_difference_that_flips_the_operating_result_is_not_fit():
    """差は300千円（DM未満）だが、書類では営業赤字△100、内訳を正とすると黒字200。結論が変わるので不適格。"""
    out = ingest("丁.xlsx", b"x", "C9", extractor=_Fixed(_lines()))
    m = out.materiality
    assert out.gate == "停止" and m["level"] == "重大"
    assert m["total_diff_thousand"] == 300                                       # 金額の基準だけなら軽微
    assert len(m["qualitative"]) == 1 and m["qualitative"][0].startswith("営業損益の符号が変わる")
    assert all(r.startswith("質的重要性") for r in m["reasons"])


@pytest.fixture()
def fin():
    return normalize(_Fixed(_lines()).ex, "丁.xlsx", "C9", "g")[0]


def test_equity_sign_flip_is_qualitatively_material(fin):
    fin.items["tna"].cur = -100                                                   # 帳簿上は債務超過
    fs = [Failure("BS内訳", "流動負債合計", "cur", 4_700, 5_000, -300)]           # 内訳では負債が300少ない
    q = ddf.qualitative(fin, fs)
    assert len(q) == 1 and q[0].startswith("純資産の符号が変わる") and "200" in q[0]


def test_cash_shortage_flip_is_qualitatively_material(fin):
    """返済後の資金収支は＋330（不足なし）。内訳を正とすると販管費が500多く、△170の不足になる。"""
    fs = [Failure("段階利益", "販管費合計", "cur", 50_600, 50_100, 500)]
    q = ddf.qualitative(fin, fs)
    assert any(s.startswith("資金不足の有無が変わる") for s in q)
    assert not any(s.startswith("営業損益") for s in q)                          # 営業赤字は赤字のまま（△100 → △600）


def test_offsetting_differences_are_judged_one_by_one_and_together(fin):
    """一つずつなら符号が変わる差は、他の差と打ち消し合っても見逃さない。"""
    fs = [Failure("段階利益", "販管費合計", "cur", 49_800, 50_100, -300),
          Failure("原価の流れ", "売上原価（調整表）", "cur", 150_300, 150_000, 300)]
    assert any(s.startswith("営業損益の符号が変わる") for s in ddf.qualitative(fin, fs))


def test_prior_period_differences_do_not_drive_the_current_diagnosis(fin):
    fs = [Failure("段階利益", "販管費合計", "prev", 49_800, 50_100, -300)]
    assert ddf.qualitative(fin, fs) == []


def test_gate_labels_cover_every_gate():
    for g in ("通過", "通過（端数調整）", "軽微", "差し替え待ち", "停止", "未確認", "対象外"):
        assert ddf.gate_label(g) != g
    assert ddf.gate_label("停止") == ddf.gate_label("未確認") == ddf.NOT_FIT
