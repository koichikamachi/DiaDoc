"""診断ミッション（主訴）と、議論ログの CSV エクスポート。台本（モック）で動かし、本物の Gemini は呼ばない。"""

from __future__ import annotations

import csv
import io
import shutil
from pathlib import Path

import pytest

from agents.base import DebateContext
from agents.growth import Growth
from agents.moderator import Judge
from agents.rebuild import Rebuild
from agents.research import Radar
from core.export import COLUMNS, rows, to_csv_bytes
from core.graph import DebateSession
from core.runs import latest_run
from state import DEFAULT_MISSION, initial_state

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


# ---------------------------------------------------------------------------
# 診断ミッション
# ---------------------------------------------------------------------------
def test_default_mission():
    from core.metrics import CashBase

    b = CashBase(liquid_funds=None, simple_cf=None, debt_service=None, free_cf=None, required_cf=None)
    assert initial_state("X", "r", b).mission == DEFAULT_MISSION == "資金ショートの回避と持続的再建方針の策定"


def test_company_mission_is_the_initial_value(data):
    s = DebateSession(latest_run("C001_sample_alpha"))
    assert "本業の収益力" in s.start().mission
    s2 = DebateSession(latest_run("C002_sample_crisis"))
    assert s2.start().mission == DEFAULT_MISSION


@pytest.mark.parametrize("agent", [Radar(), Growth(), Rebuild(), Judge()])
def test_every_agent_prompt_opens_with_the_mission(agent):
    p = agent.system_prompt("exploration", "スポンサー提携先の選定条件の整理")
    assert p.startswith("【診断ミッション】: スポンサー提携先の選定条件の整理")


def test_mission_reaches_the_speaker_and_the_context(data):
    captured = []

    class Capture:
        name = "capture"

        def generate(self, agent, system, user, schema, state, ctx):
            captured.append((agent.id, system, user))
            from agents.speakers import ScriptedSpeaker
            return ScriptedSpeaker().generate(agent, system, user, schema, state, ctx)

    s = DebateSession(latest_run("C002_sample_crisis"), speaker=Capture())
    s.set_mission("成長投資と資金繰りの両立")
    s.run_round()
    assert {a for a, _, _ in captured} == {"radar", "growth", "rebuild", "judge"}
    assert all(sys_.startswith("【診断ミッション】: 成長投資と資金繰りの両立") for _, sys_, _ in captured)
    assert all("# 診断ミッション：成長投資と資金繰りの両立" in u for _, _, u in captured)


def test_changing_the_mission_mid_debate_is_recorded(data):
    s = DebateSession(latest_run("C002_sample_crisis"))
    s.step()
    s.set_mission("事業承継に向けた企業価値の改善")
    st = s.state()
    assert st.mission == "事業承継に向けた企業価値の改善"
    assert st.messages[-1].speaker == "human" and "診断ミッションを" in st.messages[-1].text
    assert s.next_node == "growth"                               # 手番は変わらない


def test_growth_prompt_has_the_four_levers_and_the_context_shows_progress(data):
    p = Growth().system_prompt("exploration")
    for w in ("① 売上・粗利", "② 原価・現場", "③ 固定費・販管費", "④ 資産売却・BS", "パッケージ", "別のレバー"):
        assert w in p
    ctx = DebateContext.from_run(latest_run("C002_sample_crisis"))
    u = Growth().user_prompt(initial_state("C002", "r", ctx.base), ctx)
    assert "改善レバーの消化状況" in u and "未着手：売上・粗利・原価・現場・固定費・販管費・資産売却・BS" in u


# ---------------------------------------------------------------------------
# CSV エクスポート
# ---------------------------------------------------------------------------
def finished_crisis():
    s = DebateSession(latest_run("C002_sample_crisis"))
    while not s.finished:
        s.step()
    return s.state()


def test_csv_is_utf8_bom_with_the_agreed_columns(data):
    b = to_csv_bytes(finished_crisis())
    assert b.startswith(b"\xef\xbb\xbf")                           # Excel 用の BOM
    text = b.decode("utf-8-sig")
    assert text.split("\r\n")[0] == ",".join(COLUMNS)
    assert list(COLUMNS) == ["round", "step", "speaker", "message", "proposal_action", "target_account",
                             "amount_thousand", "lead_time_months", "judgement", "cash_runway",
                             "accumulated_cf", "timestamp"]


def test_csv_has_one_row_per_bridge_and_keeps_japanese(data):
    st = finished_crisis()
    recs = list(csv.DictReader(io.StringIO(to_csv_bytes(st).decode("utf-8-sig"))))
    assert len(recs) == sum(max(1, len(m.bridges)) for m in st.messages)
    officer = next(r for r in recs if r["target_account"].startswith("役員報酬"))
    assert officer["amount_thousand"] == "6000" and officer["lead_time_months"] == "1"
    assert officer["speaker"] == "Prof. Growth" and officer["proposal_action"] == "提案"
    assert officer["judgement"] == "通過"
    assert all(r["timestamp"] for r in recs)                       # 発言の時刻が入っている


def test_csv_snapshots_follow_the_judge(data):
    recs = rows(finished_crisis())
    first = recs[0]
    assert first["cash_runway"] == "5.0" and first["accumulated_cf"] == 0      # 裁定前は改善前の値
    judge3 = [r for r in recs if r["speaker"] == "Moderator Judge" and r["round"] == 3][0]
    assert judge3["accumulated_cf"] == 30_000 and judge3["cash_runway"] == "6.8"
    assert "exploration→triage_ready" in judge3["judgement"]
    cmp_ = recs[-1]
    assert cmp_["proposal_action"] == "比較" and "残余月数を超える" in cmp_["judgement"]


def test_csv_of_an_empty_debate_is_just_the_header():
    assert to_csv_bytes(None).decode("utf-8-sig").strip() == ",".join(COLUMNS)
