"""UIプロトタイプの動作確認。

同梱のサンプルデータを一時フォルダに複製して使い、本物の data/ は書き換えない。
ファイル投入窓そのものは AppTest で操作できないため、投入処理は mock_engine を直接呼んで回次の切り替えを確かめる。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "ui" / "app.py"
COMPANY = "C001_sample_alpha"


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _run() -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_initial_render_shows_real_reconciliation(data):
    at = _run()
    assert len(at.tabs) == 4
    assert at.session_state["run_select__" + COMPANY] == "run_001_initial"
    assert any("全38項目一致" in s.value for s in at.success)


def _btn(at, label):
    return next(b for b in at.button if b.label == label)


def test_cockpit_has_three_panes_and_new_tagline(data):
    at = _run()
    assert "対立仮説検証による自律型経営診断システム" in _texts(at)
    assert any("論争はまだ始まっていません" in i.value for i in at.info)


def _texts(at) -> str:
    return " ".join([m.value for m in at.markdown] + [h.proto.body for h in at.get("html")])


def test_next_turn_adds_one_card(data):
    at = _run()
    _btn(at, "▶ 1手進める").click().run()
    assert not at.exception, at.exception
    assert 'class="dd-name">Analyst Radar' in _texts(at)
    at.selectbox(key="company").set_value("C002_sample_crisis").run()
    _btn(at, "⏩ 次のラウンドへ").click().run()
    assert not at.exception, at.exception
    texts = _texts(at)
    assert "Moderator Judge" in texts and "差し戻し 1件" in texts and "必要CF" in texts


def test_triage_declaration_shows_structured_options(data):
    at = _run()
    at.selectbox(key="company").set_value("C002_sample_crisis").run()
    for _ in range(5):   # 探索3ラウンド（あがき）→ 宣告 → 比較
        _btn(at, "⏩ 次のラウンドへ").click().run()
    assert not at.exception, at.exception
    texts = _texts(at)
    assert 'class="dd-cmp"' in texts and "決め手になる事実" in texts and "残余月数を超える" in texts
    assert texts.count('class="dd-option-name"') == 6 and "詐害行為" in texts   # タイムラインと左の検討ステータスに3つずつ
    assert "Level 0：何を残し、何を捨てるか" in texts
    assert "フェーズ判定（プログラム）：探索 → トリアージ" in texts
    assert _btn(at, "▶ 1手進める").disabled                    # 論争終了後は進められない


def test_intervention_is_written_to_the_debate_state(data):
    from core.graph import DebateSession
    from core.runs import latest_run

    at = _run()
    at.text_area(key="intervene_text").input("雇用は全員維持することが前提です")
    at.button(key="FormSubmitter:intervene-介入する").click().run()
    assert not at.exception, at.exception
    st_ = DebateSession(latest_run(COMPANY)).state()
    assert [m.speaker for m in st_.messages] == ["human", "radar"]   # 介入の後、すぐ1手進んで次の発言者が答える
    assert "雇用" in st_.messages[0].text


def test_legacy_log_is_kept_in_an_expander(data):
    at = _run()
    assert any("LangGraph 接続前の台本" in c.value for c in at.caption)


def test_second_run_shows_diff_banner_and_first_run_is_read_only(data):
    from core.mock_engine import handle_upload

    handle_upload(COMPANY, "勘定科目内訳明細書.pdf", b"dummy")
    at = _run()
    assert at.session_state["run_select__" + COMPANY] == "run_002_followup"
    assert any("前回（第1次分析）からの差分" in i.value for i in at.info)
    # 第1次分析へタイムトラベル：凍結済みで論争を進められない
    at.selectbox(key="run_select__" + COMPANY).set_value("run_001_initial").run()
    assert not at.exception
    assert _btn(at, "▶ 1手進める").disabled
    assert any("凍結されました" in i.value for i in at.info)


def test_mode_toggle(data):
    at = _run()
    at.toggle[0].set_value(True).run()
    assert not at.exception


def test_crisis_model_renders_as_fictional(data):
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    at.selectbox(key="company").set_value("C002_sample_crisis").run()
    assert not at.exception, at.exception
    assert any("全38項目一致" in s.value for s in at.success)
    assert any("架空モデル" in w.value for w in at.warning)


def test_sample_company_is_shown_as_a_model_company(data):
    at = _run()
    assert not at.exception, at.exception
    assert any("アルファ製菓（東証スタンダード上場・加工食品製造モデル）" in m.value for m in at.markdown)
    assert any("モデル企業" in i.value and "係数" in i.value for i in at.info)


def test_qualitative_material_is_added_to_the_current_run(data):
    from core.graph import DebateSession
    from core.runs import latest_run

    at = _run()
    at.text_input(key="dock_name").input("銀行面談メモ")
    at.text_area(key="dock_text").input("メインバンクは3か月の元本返済猶予に前向き。")
    at.button(key="FormSubmitter:dock_quali-この回次に追加して議論を続ける").click().run()
    assert not at.exception, at.exception
    run = latest_run(COMPANY)
    assert run.run_id == "run_001_initial"                       # 回次は変わらない
    assert (run.path / "inputs" / "銀行面談メモ.md").exists()
    s = DebateSession(run)
    assert "銀行面談メモ" in s.ctx.registry                      # 次の手から引用できる
    texts = _texts(at)
    assert "途中追加" in texts or "銀行面談メモ" in texts


def test_decode_text_reads_shift_jis():
    from core.digest import decode_text

    assert decode_text("面談メモ".encode("cp932")) == "面談メモ"
    assert decode_text("面談メモ".encode("utf-8")) == "面談メモ"


def test_intervention_addressed_to_growth_jumps_the_queue(data):
    from core.graph import DebateSession
    from core.runs import latest_run

    at = _run()
    _btn(at, "▶ 1手進める").click().run()                    # radar
    at.text_area(key="intervene_text").input("いきなり8%の削減は難しいのでは？")
    at.selectbox(key="intervene_to").set_value("growth")
    at.button(key="FormSubmitter:intervene-介入する").click().run()
    assert not at.exception, at.exception
    st_ = DebateSession(latest_run(COMPANY)).state()
    assert [m.speaker for m in st_.messages] == ["radar", "human", "growth"]
    assert st_.messages[1].addressee == "growth"


def test_addressee_resets_to_auto_after_each_turn(data):
    at = _run()
    sel = at.selectbox(key="intervene_to")
    assert sel.value is None and sel.format_func(None) == "自動（指定なし）"
    at.selectbox(key="intervene_to").set_value("rebuild")
    _btn(at, "▶ 1手進める").click().run()                    # 介入せずに1手進めても、宛先は自動に戻る
    assert not at.exception, at.exception
    assert at.selectbox(key="intervene_to").value is None
    at.text_area(key="intervene_text").input("遊休地の売却は地元の反対で難しい")
    at.selectbox(key="intervene_to").set_value("growth")
    at.button(key="FormSubmitter:intervene-介入する").click().run()
    assert not at.exception, at.exception
    assert at.selectbox(key="intervene_to").value is None          # 介入して答えが出たあとも自動に戻る


def test_mission_is_shown_and_can_be_changed(data):
    from core.graph import DebateSession
    from core.runs import latest_run

    at = _run()
    assert "本業の収益力の立て直し" in _texts(at)                     # C001 の meta.json の初期値
    at.selectbox(key="mission_choice").set_value("スポンサー・提携先の選定条件の整理")
    at.button(key="mission_set").click().run()
    assert not at.exception, at.exception
    assert DebateSession(latest_run(COMPANY)).state().mission == "スポンサー・提携先の選定条件の整理"
    assert "スポンサー・提携先の選定条件の整理" in _texts(at)


def test_csv_download_buttons_appear_after_the_first_speech(data):
    at = _run()
    assert at.get("download_button") and all(b.proto.disabled for b in at.get("download_button")
                                               if b.proto.label.endswith("CSV") or "CSV出力" in b.proto.label)
    _btn(at, "▶ 1手進める").click().run()
    labels = {b.proto.label: b.proto.disabled for b in at.get("download_button")}
    assert labels.get("📥 CSV") is False and labels.get("📥 議論ログをCSV出力") is False


def test_new_company_from_the_sidebar_starts_empty_and_blocks_the_debate(data):
    at = _run()
    at.text_input(key="nc_name").input("サンプル精工")
    at.text_input(key="nc_industry").input("金属製品製造")
    at.checkbox(key="nc_fictional").check()
    at.button(key="FormSubmitter:new_company-作成する").click().run()
    assert not at.exception, at.exception
    assert at.session_state.company.startswith("C003_")
    assert any("財務データがありません" in i.value for i in at.info)
    assert _btn(at, "▶ 1手進める").disabled and _btn(at, "⏩ 次のラウンドへ").disabled


def test_next_speaker_can_be_nominated_from_the_deck(data):
    from core.graph import DebateSession
    from core.runs import latest_run

    at = _run()
    _btn(at, "▶ 1手進める").click().run()                      # radar
    at.selectbox(key="next_pick").set_value("rebuild")
    _btn(at, "▶ 1手進める").click().run()
    assert not at.exception, at.exception
    st_ = DebateSession(latest_run(COMPANY)).state()
    assert [m.speaker for m in st_.messages] == ["radar", "rebuild"] and st_.next_speaker == "growth"


def test_mismatch_report_is_shown_without_crashing(data):
    from core.mock_engine import handle_upload
    from core.runs import create_company
    from tools.file_ingest import MockExtractor

    class Broken(MockExtractor):
        name = "gemini:fake"

        def __init__(self):
            super().__init__(ROOT / "data/companies/C002_sample_crisis/runs/run_001_initial/inputs/financials.json")

        def extract(self, filename, content):
            ex = super().extract(filename, content)
            for it in ex.items:
                if it.key == "ta":
                    it.cur += 1000
            return ex

    company = create_company("サンプル精工")
    handle_upload(company, "決算報告書.pdf", b"%PDF", extractor=Broken())
    at = _run()
    at.selectbox(key="company").set_value(company).run()
    assert not at.exception, at.exception
    assert any("重大な計算不一致" in e.value and "診断プロセスを停止" in e.value for e in at.error)
    assert "資産合計" in _texts(at)


def test_minor_difference_offers_two_choices_and_adjusts(data):
    from core.mock_engine import handle_upload
    from core.runs import create_company, latest_run
    from tools.file_ingest import MockExtractor

    class Slight(MockExtractor):
        name = "gemini:fake"

        def __init__(self):
            super().__init__(ROOT / "data/companies/C002_sample_crisis/runs/run_001_initial/inputs/financials.json")

        def extract(self, filename, content):
            ex = super().extract(filename, content)
            for it in ex.items:
                if it.key == "oca":
                    it.cur += 300
            return ex

    company = create_company("端数精工")
    handle_upload(company, "決算報告書.pdf", b"%PDF", extractor=Slight())
    at = _run()
    at.selectbox(key="company").set_value(company).run()
    assert not at.exception, at.exception
    assert any("軽微な計算差異（差額: 300千円" in w.value for w in at.warning)
    labels = [b.label for b in at.button]
    assert "財務諸表を修正して差し替える" in labels and "端数調整で自動調整して診断を続行する" in labels
    next(b for b in at.button if b.label == "端数調整で自動調整して診断を続行する").click().run()
    assert not at.exception, at.exception
    assert latest_run(company).financials() is not None
    assert "端数調整差額の計上を承認" in _texts(at)                  # 監査証跡に出る
    assert any("人が承認した端数調整差額" in i.value for i in at.info)   # 検算の欄にも明示される


def test_document_preview_opens_in_a_dialog(data):
    at = _run()
    doc_btn = next(b for b in at.button if b.label == "有報第73期（モデル）")
    doc_btn.click().run()
    assert not at.exception, at.exception
    assert any("原本はシステムに保存していません" in c.value for c in at.caption)


def test_run_comparison_tab_renders(data):
    at = _run()
    _btn(at, "＋ 新しい分析回次（Run）を開始").click().run()
    assert not at.exception, at.exception
    assert len(at.multiselect(key="cmp_runs__" + COMPANY + "__2").value) == 2


def test_next_pick_defaults_to_auto_and_resets_after_a_nominated_step(data):
    at = _run()
    assert at.selectbox(key="next_pick").value == "auto"            # 「Choose an option」にならない
    _btn(at, "▶ 1手進める").click().run()
    at.selectbox(key="next_pick").set_value("rebuild")
    _btn(at, "▶ 1手進める").click().run()
    assert at.selectbox(key="next_pick").value == "auto"            # 指名は1手ごとに自動へ戻る


def test_bottom_buttons_under_the_latest_speech(data):
    from core.graph import DebateSession
    from core.runs import latest_run

    at = _run()
    _btn(at, "▶ 1手進める").click().run()
    bottom = at.button(key="step_bottom")
    assert bottom.label.startswith("▶ 次の1手（次：Prof. Growth")
    bottom.click().run()
    assert not at.exception, at.exception
    assert [m.speaker for m in DebateSession(latest_run(COMPANY)).state().messages] == ["radar", "growth"]
    at.button(key="gate_bottom").click().run()
    assert DebateSession(latest_run(COMPANY)).state().round == 2


def test_stale_double_click_is_ignored(data):
    from core.graph import DebateSession
    from core.runs import latest_run

    at = _run()
    at.session_state["dd_pending"] = {"action": "step", "nonce": 5, "speaker": None}   # 古い発言数の要求
    at.run()
    assert not DebateSession(latest_run(COMPANY)).started or not DebateSession(latest_run(COMPANY)).state().messages


def test_status_names_say_review_not_adoption(data):
    at = _run()
    for _ in range(2):
        _btn(at, "⏩ 次のラウンドへ").click().run()
    texts = _texts(at)
    assert "審査通過・時期内" in texts and "採用候補" not in texts.split("採否ステータス")[-1]
    assert "贈答・高付加価値ラインへの移行" in texts and "本文を読む" in texts


def test_matrix_shows_basis_table_and_plain_recon_wording(data):
    at = _run()
    assert any("この数字は論争の根拠に使えます" in s.value for s in at.success)
    assert any("グラフの基礎数値と典拠" in m.value for m in at.markdown)
    labels = [m.label for m in at.metric]
    assert "受取配当" not in "".join(labels[:7]) and "経常利益に占める受取配当金" in labels and "残余月数（改善前）" in labels
    at.selectbox(key="company").set_value("C002_sample_crisis").run()
    labels = [m.label for m in at.metric]
    assert "経常利益に占める受取配当金" not in labels and not at.exception


def test_benchmark_is_labelled_with_the_official_survey(data):
    at = _run()
    assert not at.exception, at.exception
    assert any("比較基準：中小企業実態基本調査（製造業統計）" in m.value for m in at.markdown)
    assert not any("仮置き" in w.value for w in at.warning)
