"""ファイル読み取り（tools.file_ingest）と検算ゲート連携のテスト。

実際の Gemini API は呼ばない。代わりに、
- MockExtractor（APIキーなし時の代役）で制作サンプルが検算を通ること
- 偽の Gemini クライアントで、プロンプト・構造化出力の指定・LLM出力の検証（別名の吸収、null、未知キー）
を確かめる。
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
from tools import standard_accounts as sa
from tools.file_ingest import (
    Extraction,
    ExtractedItem,
    GeminiExtractor,
    MockExtractor,
    excel_to_text,
    get_extractor,
    ingest,
    merge_missing,
    normalize,
)

ROOT = Path(__file__).resolve().parents[1]
COMPANY = "C001_sample_alpha"


class FakeModels:
    def __init__(self, extraction: Extraction):
        self.extraction = extraction
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        return SimpleNamespace(parsed=None, text=self.extraction.model_dump_json())


class FakeClient:
    def __init__(self, extraction: Extraction):
        self.models = FakeModels(extraction)


def _sga_extraction() -> Extraction:
    """販管費内訳を読んだ想定の出力。別名・null・未知キー・重複を含む。"""
    return Extraction(
        document_type="販売費及び一般管理費の内訳", fiscal_period="第73期", unit="千円", rounding="千円未満切捨て",
        items=[
            ExtractedItem(key="unknown", source_label="発送配達費", cur=2188364, page="98"),  # 別名 → sga_freight
            ExtractedItem(key="sga_adv", source_label="広告宣伝費", cur=410000, page="98"),
            ExtractedItem(key="sga_promo", source_label="販売促進費", cur=None, page="98"),  # 判読不能 → null
            ExtractedItem(key="made_up_key", source_label="謎の科目", cur=123, page="98"),  # 捨てる
            ExtractedItem(key="unknown", source_label="減価償却費", cur=50000, page="98"),  # 曖昧 → 捨てる
            ExtractedItem(key="sga_adv", source_label="広告費", cur=410000, page="99"),  # 同じ値の重複 → 統合
            ExtractedItem(key="sga_salary", source_label="給料及び手当", cur=959114, page="74"),  # 連結の注記
            ExtractedItem(key="sga_salary", source_label="給料及び手当", cur=801000, page="98"),  # 単体の注記 → 食い違い
        ],
        unreadable=["販売促進費（かすれ）"],
    )


# ---------------------------------------------------------------------------
# 抽出器の選択
# ---------------------------------------------------------------------------
def test_without_api_key_the_mock_is_used(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert isinstance(get_extractor(), MockExtractor)


def test_with_api_key_gemini_is_used(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.delenv("DBD_EXTRACTOR", raising=False)
    ex = get_extractor()
    assert isinstance(ex, GeminiExtractor)
    assert ex.model == config.gemini_model()


def test_mock_can_be_forced(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setenv("DBD_EXTRACTOR", "mock")
    assert isinstance(get_extractor(), MockExtractor)


# ---------------------------------------------------------------------------
# モックのフォールバック：制作サンプルで検算ゲートを通る
# ---------------------------------------------------------------------------
def test_mock_pipeline_passes_reconciliation_gate():
    out = ingest("anything.pdf", b"%PDF", COMPANY, MockExtractor())
    assert out.report.is_mock
    assert out.gate == "通過"
    assert out.reconciliation.total == 38
    assert out.reconciliation.count("一致") == 38
    assert out.reconciliation.count("不一致") == 0
    assert out.financials.items["sales"].cur == 27328784


def test_misread_number_stops_the_gate():
    ex = MockExtractor().extract("x.pdf", b"")
    for it in ex.items:
        if it.key == "cash":
            it.cur += 500  # Gemini が1桁読み違えた想定
    fin, rep = normalize(ex, "x.pdf", COMPANY, "gemini:test")
    from core.guardrails import reconcile

    assert not reconcile(fin).passed


# ---------------------------------------------------------------------------
# Gemini 経路（偽クライアント）
# ---------------------------------------------------------------------------
def test_gemini_request_uses_prompt_rules_and_json_schema():
    client = FakeClient(_sga_extraction())
    GeminiExtractor(client=client, model="gemini-test").extract("販管費内訳.pdf", b"%PDF-1.4")
    call = client.models.calls[0]
    assert call.model == "gemini-test"
    prompt = call.contents[-1]
    assert "推測せず null（未確認）" in prompt
    assert "シノニム" in prompt and "荷造運賃＝発送費" in prompt
    assert "sga_adv: 広告宣伝費" in prompt  # 標準科目一覧が渡っている
    assert "個別（単体）の財務諸表の数値を抽出せよ" in prompt  # 有報は連結と単体の両方を含む
    assert "「－」「―」「—」と書かれているものは「金額ゼロ」" in prompt  # 実証テストで判明した約束
    assert "dvd: 剰余金の配当" in prompt and "減少額を正の数で書く" in prompt
    assert call.config.automatic_function_calling.disable is True
    assert call.config.response_mime_type == "application/json"
    assert call.config.response_schema is Extraction
    assert call.config.temperature == 0
    assert getattr(call.contents[0], "inline_data", None) is not None  # PDFはバイナリのまま渡す


def test_llm_output_is_validated_and_synonyms_absorbed():
    ex = GeminiExtractor(client=FakeClient(_sga_extraction()), model="m").extract("販管費内訳.pdf", b"%PDF")
    fin, rep = normalize(ex, "販管費内訳.pdf", COMPANY, "gemini:m")
    assert fin.items["sga_freight"].cur == 2188364
    assert fin.items["sga_freight"].source_label == "発送配達費"
    assert "発送配達費 → 荷造運賃" in rep.remapped
    assert fin.items["sga_promo"].cur is None and "販売促進費" in rep.unverified  # null は null のまま
    assert any("謎の科目" in d for d in rep.dropped)
    assert any("減価償却費" in d for d in rep.dropped)  # 曖昧な語は自動で当てはめない
    assert fin.items["sga_adv"].cur == 410000  # 同じ値の重複は統合
    assert fin.items["sga_salary"].cur is None  # 値が食い違う重複は推測で選ばず未確認
    assert any("給料手当：値が食い違うため未確認" in d and "p.74" in d and "p.98" in d for d in rep.duplicates)
    assert any("区分を確かめられない" in w for w in rep.warnings)
    assert fin.items["sga_adv"].source.file == "販管費内訳.pdf" and fin.items["sga_adv"].source.page == "98"
    assert rep.unreadable == ["販売促進費（かすれ）"]


def test_partial_document_is_outside_the_gate():
    out = ingest("販管費内訳.pdf", b"%PDF", COMPANY, GeminiExtractor(client=FakeClient(_sga_extraction()), model="m"))
    assert out.gate == "対象外" and out.reconciliation is None


@pytest.mark.parametrize(("unit", "note", "rounding"), [
    ("円", None, "yen"), ("千円", "千円未満切捨て", "truncate_thousand"), ("千円", "千円未満四捨五入", "round_thousand"),
    ("百万円", None, "truncate_thousand"), (None, None, "truncate_thousand"),
])
def test_unit_decides_rounding_rule(unit, note, rounding):
    fin, rep = normalize(Extraction(document_type="BS", unit=unit, rounding=note), "a.pdf", COMPANY, "gemini:m")
    assert fin.rounding == rounding
    if unit is None or note is None and unit != "円":
        assert rep.warnings


# ---------------------------------------------------------------------------
# Excel の取り込みと統合
# ---------------------------------------------------------------------------
def test_excel_is_converted_to_text_with_sheet_names():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "販管費内訳"
    ws.append(["科目", "当期"])
    ws.append(["荷造運賃", 2188364])
    buf = io.BytesIO()
    wb.save(buf)
    text = excel_to_text(buf.getvalue())
    assert "### シート：販管費内訳" in text and "荷造運賃\t2188364" in text


def test_unsupported_format_is_rejected():
    from tools.file_ingest import to_parts

    with pytest.raises(ValueError):
        to_parts("memo.docx", b"")


def test_merge_fills_only_missing_and_reports_conflicts():
    base, _ = normalize(MockExtractor().extract("a", b""), "有報", COMPANY, "mock")
    new, _ = normalize(_sga_extraction(), "販管費内訳.pdf", COMPANY, "gemini:m")
    new.items["sales"] = base.items["sales"].model_copy(update={"cur": 1})  # 食い違い
    merged, conflicts = merge_missing(base, new)
    assert merged.items["sga_freight"].cur == 2188364  # 欠けていた科目は埋まる
    assert merged.items["sales"].cur == 27328784  # 既存の値は上書きしない
    assert any("売上高" in c for c in conflicts)


def test_standard_catalog_covers_sample_keys():
    sample = json.loads((ROOT / "data/companies/C001_sample_alpha/runs/run_001_initial/inputs/financials.json")
                        .read_text(encoding="utf-8"))
    assert set(sample["items"]) <= sa.KEYS


# ---------------------------------------------------------------------------
# 資料投入の流れ（回次・データ請求との連携）
# ---------------------------------------------------------------------------
@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_upload_with_mock_says_it_did_not_read_the_file(data):
    from core.mock_engine import handle_upload

    run, added, _ = handle_upload(COMPANY, "販管費内訳.pdf", b"%PDF", extractor=MockExtractor())
    radar = next(m for m in added if m["who"] == "radar")
    assert "モック" in radar["text"] and "中身は読まず" in radar["text"]
    assert "検算ゲート：全38項目中 一致38" in radar["text"]
    reqs = {r["id"]: r for r in run.read("data_requests.json")}
    assert reqs["R1"]["status"] == "受領（検証待ち）"  # モックでは「解消」にしない
    assert (run.path / "extracted" / "販管費内訳.json").exists()


def test_upload_with_gemini_resolves_request_with_sourced_value(data):
    from core.mock_engine import handle_upload

    ext = GeminiExtractor(client=FakeClient(_sga_extraction()), model="m")
    run, added, _ = handle_upload(COMPANY, "販管費内訳.pdf", b"%PDF", extractor=ext)
    reqs = {r["id"]: r for r in run.read("data_requests.json")}
    assert reqs["R1"]["status"] == "解消"
    assert reqs["R1"]["resolved_by"][0]["source"] == {"file": "販管費内訳.pdf", "page": "98"}
    assert reqs["R2"]["status"] == "受領（検証待ち）"  # 販売促進費は null（未確認）なので解消しない
    radar = next(m for m in added if m["who"] == "radar")
    assert "R1 広告宣伝費 は数値を取得したため「解消」" in radar["text"]


def test_upload_survives_extraction_failure(data):
    from core.mock_engine import handle_upload

    class Broken:
        name = "gemini:broken"

        def extract(self, filename, content):
            raise RuntimeError("quota exceeded")

    run, added, _ = handle_upload(COMPANY, "販管費内訳.pdf", b"%PDF", extractor=Broken())
    assert (run.path / "inputs" / "販管費内訳.pdf").exists()
    assert any("読み取りに失敗しました（quota exceeded）" in m["text"] for m in added)


# ---------------------------------------------------------------------------
# 実証テスト（2026-09-27、gemini-3.8-flash で第73期有報PDFを読んだ結果）から作った回帰テスト
#   244件中 一致233件。食い違い2件は配当の符号（△を負で記録）、読み取りなし9件はすべて「－」表示のゼロ
# ---------------------------------------------------------------------------
DASH_ZERO_ITEMS = [("ada1", "cur"), ("cbond", "prev"), ("ctax", "cur"), ("ltd", "cur"), ("bde", "prev"),
                   ("sg2", "prev"), ("sl2", "prev"), ("sl5", "cur"), ("emd", "prev")]


def _as_read_by_gemini_on_2026_09_27() -> Extraction:
    ex = MockExtractor().extract("73_securities-report.pdf", b"")
    for it in ex.items:
        if it.key == "dvd":
            it.prev, it.cur = -it.prev, -it.cur  # △240,240、△313,354 を負で記録
        for key, period in DASH_ZERO_ITEMS:
            if it.key == key:
                setattr(it, period, None)  # 「－」を null（未確認）として記録
    return ex


def test_regression_negative_dividend_is_normalized_and_gate_no_longer_stops():
    from core.guardrails import reconcile

    fin, rep = normalize(_as_read_by_gemini_on_2026_09_27(), "73_securities-report.pdf", COMPANY, "gemini:m")
    assert fin.items["dvd"].cur == 313354 and fin.items["dvd"].prev == 240240
    assert any("剰余金の配当" in r and "符号を正に統一" in r for r in rep.remapped)
    rec = reconcile(fin)
    assert rec.count("不一致") == 0  # 当日は「繰越利益剰余金の動き」が差626,708で停止していた
    assert rec.count("未確認") == 7  # 「－」が null のままなら、その項目を含む検算は未確認に留まる


def test_regression_the_nine_missing_values_are_all_zero_in_the_truth():
    truth = MockExtractor().extract("a", b"")
    vals = {it.key: it for it in truth.items}
    assert all(getattr(vals[k], p) == 0 for k, p in DASH_ZERO_ITEMS)


# ---------------------------------------------------------------------------
# 販売費・一般管理費の区分開示（2回目の実証テスト、有報第73期 p.100 の実際の値）
# ---------------------------------------------------------------------------
P100 = [  # (key, 科目名, 販売費 前期・当期, 一般管理費 前期・当期)
    ("sga_salary", "給料及び手当", (465322, 469368), (253364, 269244)),
    ("sga_bonus", "賞与引当金繰入額", (65358, 66882), (39430, 42865)),
    ("sga_retire", "退職給付費用", (20691, 18992), (15612, 14700)),
    ("sga_dep", "減価償却費", (9248, 9593), (57057, 89934)),
]


def _p100(sections=("販売費", "一般管理費")) -> Extraction:
    items = []
    for key, label, sell, adm in P100:
        items.append(ExtractedItem(key=key, source_label=label, prev=sell[0], cur=sell[1], page="100", section=sections[0]))
        items.append(ExtractedItem(key=key, source_label=label, prev=adm[0], cur=adm[1], page="100", section=sections[1]))
    return Extraction(document_type="有価証券報告書", unit="千円", items=items)


def test_selling_and_admin_split_is_summed_and_breakdown_kept():
    fin, rep = normalize(_p100(), "73_securities-report.pdf", COMPANY, "gemini:m")
    for key, _, sell, adm in P100:
        it = fin.items[key]
        assert (it.prev, it.cur) == (sell[0] + adm[0], sell[1] + adm[1])
        assert [(c.section, c.cur) for c in it.breakdown] == [("販売費", sell[1]), ("一般管理費", adm[1])]
    assert fin.items["sga_salary"].cur == 738612
    assert rep.unverified == []  # 2回目の実証で残った未確認4件が解消する
    assert any("給料手当：販売費と一般管理費に区分開示 → 合計を採用（当期 469,368＋269,244＝738,612）" in d
               for d in rep.duplicates)
    assert not rep.warnings or all("区分を確かめられない" not in w for w in rep.warnings)


@pytest.mark.parametrize("sections", [("販売費のうち主要な費目", "一般管理費のうち主要な費目"), ("販売費", "管理費")])
def test_section_names_are_recognized_loosely(sections):
    fin, _ = normalize(_p100(sections), "a.pdf", COMPANY, "gemini:m")
    assert fin.items["sga_salary"].cur == 738612


def test_consolidated_and_standalone_conflict_stays_unverified():
    fin, rep = normalize(_p100(("連結注記", "単体注記")), "a.pdf", COMPANY, "gemini:m")
    assert fin.items["sga_salary"].cur is None
    assert any("値が食い違うため未確認（区分：単体注記・連結注記）" in d for d in rep.duplicates)


def test_split_with_one_side_missing_is_not_summed():
    ex = _p100()
    ex.items[1].cur = None  # 一般管理費の給料（当期）が判読不能
    fin, rep = normalize(ex, "a.pdf", COMPANY, "gemini:m")
    assert fin.items["sga_salary"].cur is None and fin.items["sga_salary"].prev == 465322 + 253364
    assert any("当期は片方が未確認のため合計せず" in d for d in rep.duplicates)


def test_split_rule_applies_only_to_sga_detail_accounts():
    ex = Extraction(document_type="x", unit="千円", items=[
        ExtractedItem(key="sales", source_label="売上高", cur=100, section="販売費"),
        ExtractedItem(key="sales", source_label="売上高", cur=200, section="一般管理費")])
    fin, _ = normalize(ex, "a.pdf", COMPANY, "gemini:m")
    assert fin.items["sales"].cur is None  # 売上高を足し合わせたりはしない


def test_prompt_asks_for_section_and_forbids_summing():
    client = FakeClient(_p100())
    GeminiExtractor(client=client, model="m").extract("a.pdf", b"%PDF")
    prompt = client.models.calls[0].contents[-1]
    assert "section に「販売費」または「一般管理費」と書け。合計は計算するな" in prompt
