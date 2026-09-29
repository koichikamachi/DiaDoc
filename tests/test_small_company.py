"""中小企業の決算書（一期だけ・合計行が少ない・内訳の書き方が違う）でも、検算ゲートが中身を確かめること。

2026-09-29 の臨床テストで、一期だけの Excel が「一致0・未確認38・不一致0」のまま通過し、財務データに採用された。
その再発防止。数値はテスト用の架空会社（乙精機）で、構造だけを当日の資料に合わせてある：
売上原価の記載額と製造原価の内訳の積み上げに差があり、販管費の記載額と費目の合計にも差がある。
"""

from __future__ import annotations

import pytest

from core.guardrails import core_unverified, reconcile
from tools.file_ingest import Extraction, ExtractedItem, ingest, normalize

BS, PL = "貸借対照表", "損益計算書"
SGA = "販売費及び一般管理費"

LINES = [  # (key, 原資料の科目名, 当期, 区分)
    ("cash", "現金及び預金", 20000, BS), ("nr", "受取手形", 1000, BS), ("ar", "売掛金", 9000, BS),
    ("stock", "棚卸資産（材料・仕掛品）", 2000, BS), ("oca", "その他流動資産", 3000, BS), ("tca", "流動資産合計", 35000, BS),
    ("land", "土地", 50000, BS), ("bld", "建物及び附属設備", 40000, BS), ("mac", "機械装置及びその他", 10000, BS),
    ("tppe", "（有形固定資産合計）", 100000, BS), ("tint", "（無形固定資産合計）", 0, BS),
    ("inv", "投資有価証券", 500, BS), ("oinv", "保険積立金・その他", 9500, BS), ("tinv", "（投資その他の資産合計）", 10000, BS),
    ("tfa", "固定資産合計", 110000, BS), ("ta", "資産合計", 145000, BS),
    ("np", "支払手形", 1500, BS), ("ap", "買掛金", 500, BS), ("stl", "短期借入金", 10000, BS),
    ("unknown", "未払金・未払費用", 8000, BS), ("tcl", "流動負債合計", 20000, BS),
    ("ltd", "長期借入金", 100000, BS), ("tltl", "固定負債合計", 100000, BS), ("tl", "負債合計", 120000, BS),
    ("cs", "資本金", 10000, BS), ("re", "利益剰余金（繰越利益剰余金）", 15000, BS), ("tsh", "株主資本合計", 25000, BS),
    ("tna", "純資産合計", 25000, BS), ("tle", "負債・純資産合計", 145000, BS),
    ("sales", "売上高", 200000, PL), ("cogs", "売上原価", 160000, PL),
    ("bmat", "（期首材料棚卸高）", 1000, PL), ("mpur", "（当期材料仕入高）", 20000, PL), ("lab", "（労務費・人件費）", 60000, PL),
    ("exp", "（製造経費・外注加工費）", 70000, PL), ("emat", "（期末材料棚卸高）", 500, PL), ("wip_chg", "（仕掛品増減）", 500, PL),
    ("gp", "売上総利益", 40000, PL), ("sga", "販売費及び一般管理費", 44000, PL),
    ("sga_officer", "役員報酬", 15000, SGA), ("sga_salary", "給料手当（販管）", 8000, SGA),
    ("sga_supplies", "工場消耗品・消耗品費", 5000, SGA), ("sga_insurance", "保険料", 4000, SGA), ("sga_misc", "雑費・その他販管費", 10000, SGA),
    ("op", "営業利益", -4000, PL), ("tnoi", "営業外収益", 3000, PL), ("tnoe", "営業外費用", 0, PL),
    ("ord", "経常利益", -1000, PL), ("tsg", "特別利益", 0, PL), ("tsl", "特別損失", 100, PL),
    ("pbt", "税引前当期純利益", -1100, PL), ("ctx", "法人税、住民税及び事業税", 70, PL), ("ni", "当期純利益", -1170, PL),
]


def _extraction(lines=LINES) -> Extraction:
    return Extraction(document_type="財務諸表", company_name="乙精機（架空）", fiscal_period="第10期", unit="千円",
                      items=[ExtractedItem(key=k, source_label=label, cur=v, page=sec, section=sec)
                             for k, label, v, sec in lines])


class _Fixed:
    name = "gemini:fake"

    def __init__(self, ex: Extraction):
        self.ex = ex

    def extract(self, filename, content):
        return self.ex


@pytest.fixture()
def fin():
    return normalize(_extraction(), "財務諸表_乙精機_第10期.xlsx", "C9", "gemini:fake")[0]


def test_single_period_statement_is_checked_on_the_current_period(fin):
    rec = reconcile(fin)
    assert all(p.period == "cur" for c in rec.checks for p in c.periods)           # 前期の欄がないので前期は見ない
    by = {(c.group, c.name): c.status for c in rec.checks}
    assert by[("BS内訳", "流動資産合計")] == "一致"                                  # 書類にない内訳（前払費用など）は0
    assert by[("BS内訳", "株主資本合計")] == "一致"                                  # 利益剰余金合計の行がなくても内訳から組み立てる
    assert by[("段階利益", "当期純利益")] == "一致"                                  # 法人税等合計の行がなくても法人税等から
    assert by[("段階利益", "営業外収益合計")] == "未確認"                            # 合計だけの行は確かめようがない（不一致にしない）
    assert core_unverified(rec) == []


def test_the_two_discrepancies_in_the_source_are_found(fin):
    rec = reconcile(fin)
    bad = {c.name: c.periods[0].diff for c in rec.checks if c.status == "不一致"}
    assert bad == {"販管費合計": -2000, "売上原価（調整表）": -9000}                 # 費目別の販管費、材料の受払いからの売上原価


def test_the_gate_stops_such_a_statement_as_major():
    out = ingest("財務諸表_乙精機_第10期.xlsx", b"x", "C9", extractor=_Fixed(_extraction()))
    assert out.gate == "停止" and out.materiality["level"] == "重大"


def test_composite_line_is_mapped_to_its_first_account(fin):
    assert fin.items["oap"].cur == 8000 and fin.items["oap"].source_label == "未払金・未払費用"


def test_dropped_line_with_an_amount_is_reported_and_breaks_the_subtotal():
    lines = [(("unknown",) + t[1:]) if t[1] == "保険積立金・その他" else t for t in LINES]
    fin, rep = normalize(_extraction(lines), "x.xlsx", "C9", "gemini:fake")
    assert rep.dropped_values == [{"label": "保険積立金・その他", "section": BS, "prev": None, "cur": 9500, "page": BS}]
    by = {c.name: c for c in reconcile(fin).checks}
    assert by["投資その他の資産合計"].status == "不一致" and by["投資その他の資産合計"].periods[0].diff == -9500


def test_nothing_verified_is_never_passed():
    """中心の検算が確かめられない書類は、不一致がなくても通さない（当日の不具合）。"""
    detail = ("bmat", "mpur", "lab", "exp", "emat", "wip_chg", "sga_officer", "sga_salary", "sga_supplies",
              "sga_insurance", "sga_misc")                                                # 差のある内訳を外して不一致をなくす
    lines = [t for t in LINES if t[0] not in ("tl", "tcl", "tltl") + detail]          # 負債の合計行が読めなかった
    out = ingest("x.xlsx", b"x", "C9", extractor=_Fixed(_extraction(lines)))
    assert out.gate == "未確認" and "負債合計" in out.materiality["unverified_core"]
    assert "確かめられないため停止" in out.summary()


def test_labels_in_brackets_and_with_qualifiers_are_recognized():
    from tools.standard_accounts import key_for_label

    assert key_for_label("（期首材料棚卸高）") == "bmat" and key_for_label("給料手当（販管）") == "sga_salary"
    assert key_for_label("支払手形") == "np" and key_for_label("工場消耗品・消耗品費") == "sga_supplies"
    assert key_for_label("（労務費・人件費）") is None                                  # 推測はしない（Gemini の key に任せる）


def test_dock_explains_why_the_gate_stopped(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from core.mock_engine import handle_upload
    from core.runs import create_company

    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    company = create_company("乙精機", fictional=True)
    lines = [(("unknown",) + t[1:]) if t[1] == "保険積立金・その他" else t for t in LINES]
    run, added, _ = handle_upload(company, "財務諸表_乙精機_第10期.xlsx", b"x", extractor=_Fixed(_extraction(lines)))
    assert run.financials() is None                                             # 止めた資料は採用しない
    assert any("重大な計算不一致" in m["text"] for m in added)
    at = AppTest.from_file(str(root / "src/ui/app.py"), default_timeout=30)
    at.run()
    at.selectbox(key="company").set_value(company).run()
    assert not at.exception, at.exception
    assert any("重大な計算不一致" in e.value for e in at.error)
    assert any("当てはめられなかった行" in m.value for m in at.markdown)
    assert any("「保険積立金・その他」の金額と一致" in c.value for c in at.caption)   # 差額 9,500 を説明できる行だけを名指し


# ---------------------------------------------------------------------------
# 参考表示・集計行（2026-09-29 の臨床テスト：「（参考）借入金合計」を読み取れなかった行として警告した）
# ---------------------------------------------------------------------------
REF = ("unknown", "（参考）借入金合計", 110000, BS)


def test_reference_line_is_kept_out_of_the_statement():
    fin, rep = normalize(_extraction(LINES + [REF]), "x.xlsx", "C9", "gemini:fake")
    assert rep.dropped_values == [] and rep.reference_lines[0]["label"] == "（参考）借入金合計"
    assert fin.items["ltd"].cur == 100000 and fin.items["stl"].cur == 10000


def test_reference_line_is_excluded_even_if_the_reader_gave_it_a_real_key():
    """読み取り側が「（参考）借入金合計」に長期借入金の key を付けても、本表の長期借入金は変わらない。"""
    fin, rep = normalize(_extraction(LINES + [("ltd", "（参考）借入金合計", 110000, BS)]), "x.xlsx", "C9", "g")
    assert fin.items["ltd"].cur == 100000 and len(rep.reference_lines) == 1


def test_aggregate_row_overlapping_a_detail_account_is_set_aside():
    fin, rep = normalize(_extraction(LINES + [("ltd", "借入金合計", 110000, BS)]), "x.xlsx", "C9", "g")
    assert fin.items["ltd"].cur == 100000
    assert rep.reference_lines[0]["label"] == "借入金合計" and "重複" in rep.reference_lines[0]["reason"]
    by = {c.name: c.status for c in reconcile(fin).checks}
    assert by["固定負債合計"] == "一致"


def test_warning_names_only_lines_that_explain_the_difference():
    from core.digest import dropped_explaining

    fails = [{"name": "投資その他の資産合計", "period": "当期", "diff": -9500, "tolerance": 2},
             {"name": "販管費合計", "period": "当期", "diff": -2000, "tolerance": 5}]
    rec = {"failed_checks": fails, "report": {"dropped_values": [
        {"label": "保険積立金・その他", "cur": 9500}, {"label": "謎の行", "cur": 777}]}}
    assert dropped_explaining(rec) == ["保険積立金・その他"]
    rec["report"]["dropped_values"] = [{"label": "謎の行", "cur": 777}]
    assert dropped_explaining(rec) == []                                             # 無関係な行では注意しない


def test_old_records_show_reference_lines_apart(tmp_path, monkeypatch):
    """修正前の読み取り記録（参考表示が捨てた行に入っている）でも、画面では参考表示として分けて出す。"""
    import json
    import shutil
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from core.mock_engine import handle_upload
    from core.runs import create_company

    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    company = create_company("乙精機", fictional=True)
    run, _, _ = handle_upload(company, "b.xlsx", b"x", extractor=_Fixed(_extraction()))
    rec_path = run.path / "extracted" / "b.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    rec["report"]["dropped_values"] = [{"label": "（参考）借入金合計", "section": BS, "prev": None, "cur": 110000, "page": BS}]
    rec["report"].pop("reference_lines", None)
    rec_path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    at = AppTest.from_file(str(root / "src/ui/app.py"), default_timeout=30)
    at.run()
    at.selectbox(key="company").set_value(company).run()
    assert not at.exception, at.exception
    assert not any("当てはめられなかった行" in m.value for m in at.markdown)
    assert any("本表の数値ではないため" in c.value for c in at.caption)                  # 参考表示の説明だけが出る
    assert not any("可能性があります" in c.value for c in at.caption)
