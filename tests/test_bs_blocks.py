"""比例縮尺の貸借対照表と実質化の調整（帳簿＋調整）。本物の Gemini は呼ばない。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core import adjust, metrics
from core.runs import latest_run
from schema import Adjustment

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def alpha():
    return latest_run("C001_sample_alpha").financials()


@pytest.fixture(scope="module")
def crisis():
    return latest_run("C002_sample_crisis").financials()


@pytest.fixture()
def data(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    monkeypatch.setenv("DBD_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


GAIN = Adjustment(id="A1", account="投資有価証券", key="inv", block="投資その他の資産", amount=3_000, note="時価")
SUSP = Adjustment(id="A2", account="仮払金", key="suspense", block="その他の流動資産", amount=-2_300)


def _sums(blocks):
    return (sum(b.amount for b in blocks if b.side == "資産"), sum(b.amount for b in blocks if b.side != "資産"))


@pytest.mark.parametrize("extra", [(), (GAIN,), (GAIN, SUSP)])
@pytest.mark.parametrize("name", ["alpha", "crisis"])
def test_blocks_add_up_to_the_balance_sheet(request, name, extra):
    fin = request.getfixturevalue(name)
    for mode in ("nominal", "real"):
        a, c = _sums(metrics.bs_blocks(fin, mode, extra))
        bs = metrics.balance_sheet(fin, mode, extra)
        assert a == bs["総資産"]
        assert abs(c - (bs["負債"] + bs["純資産"])) <= 2      # 原資料の千円未満切捨てによる差だけ


def test_book_blocks_keep_watch_items_where_booked(crisis):
    """仮払金などは帳簿の区画のまま（図の中で動かさない）。"""
    nom = {b.label: b.amount for b in metrics.bs_blocks(crisis, "nominal")}
    assert nom["その他の流動資産"] == 400_000 - 51_000 and nom["固定負債"] == 389_600 and nom["純資産"] == 44_710


def test_no_adjustment_means_book_equals_real(crisis):
    assert metrics.real_adjustments(crisis) == []
    assert metrics.balance_sheet(crisis, "real") == {**metrics.balance_sheet(crisis, "nominal"),
                                                     "注記": metrics.balance_sheet(crisis, "real")["注記"]}
    assert "取得原価" in metrics.balance_sheet(crisis, "real")["注記"]


def test_human_gain_and_loss_flow_to_equity(crisis):
    real = metrics.balance_sheet(crisis, "real", [GAIN, SUSP])
    assert real["総資産"] == 890_500 + 3_000 - 2_300
    assert real["純資産"] == 44_710 + 700 and real["負債"] == 845_790
    liab = Adjustment(id="A3", account="役員借入金", block="固定負債", amount=-30_000, note="債務免除の手続き済み")
    assert metrics.balance_sheet(crisis, "real", [liab])["純資産"] == 44_710 + 30_000


def test_hatched_caps_nominal_removes_real_adds(crisis):
    nom = [b for b in metrics.bs_blocks(crisis, "nominal", [GAIN, SUSP]) if b.adjust]
    real = [b for b in metrics.bs_blocks(crisis, "real", [GAIN, SUSP]) if b.adjust]
    assert [(b.label, b.amount, b.adjust) for b in nom] == [("仮払金", 2_300, "除く")]
    assert {(b.label, b.amount, b.adjust) for b in real} == {("投資有価証券", 3_000, "加える"),
                                                              ("調整による純資産の増加", 700, "加える")}


def test_disclosed_gain_is_automatic_for_listed_company(alpha):
    auto = metrics.disclosed_adjustments(alpha)
    assert {a.origin for a in auto} == {"開示"} and auto[0].amount == -61_289_707
    assert metrics.balance_sheet(alpha, "real")["純資産"] == 27_274_100
    nom_caps = {b.label for b in metrics.bs_blocks(alpha, "nominal") if b.adjust}
    assert "投資有価証券（時価評価の含み益）" in nom_caps and "繰延税金負債" in nom_caps


def test_watch_items_include_stocks_and_officer_loan(alpha, crisis):
    w = {x[1]: x for x in metrics.watch_items(crisis)}
    assert list(w) == ["投資有価証券", "土地", "仮払金", "保険積立金", "役員借入金"]
    assert "取得原価" in w["投資有価証券"][4] and w["役員借入金"][3] == "固定負債"
    assert "手続き" in w["役員借入金"][4]
    stocks = next(x for x in metrics.watch_items(alpha) if x[1] == "投資有価証券")
    assert "自動" in stocks[4]


def test_store_add_remove_and_inherit(data):
    run = latest_run("C002_sample_crisis")
    a = adjust.add(run, "投資有価証券", "投資その他の資産", 3_000, "時価", "inv")
    assert a.id == "A1" and [x.id for x in adjust.load(run)] == ["A1"]
    with pytest.raises(ValueError):
        adjust.add(run, "仮払金", "その他の流動資産", 0)
    assert adjust.remove(run, "A1").account == "投資有価証券" and adjust.load(run) == []


def test_adjustment_reaches_the_debate_context(data):
    from agents.base import DebateContext, context_text
    from core.graph import DebateSession
    from core.interrupt import intervene

    run = latest_run("C002_sample_crisis")
    a = adjust.add(run, "投資有価証券", "投資その他の資産", 3_000, "銘柄Xの時価", "inv")
    s = DebateSession(run)
    s.ctx.adjustments = adjust.load(run)
    msg = intervene(s, adjust.intervention_text(a))
    assert msg.speaker == "human" and "実質化の調整" in msg.text
    text = context_text(s.state(), DebateContext.from_run(run))
    assert "人間の介入］投資有価証券 +3,000千円" in text and "純資産 44,710 → 47,710" in text
    s.close()


def test_caption_and_chart(alpha, crisis):
    from ui.components.matrix import _bs_caption, _bs_chart

    assert _bs_caption(crisis).startswith("実質化の調整はまだありません")
    assert {x for t in _bs_chart(crisis).data for x in t.x[0]} == {"帳簿＝実質（調整なし）"}
    assert {x for t in _bs_chart(crisis, [GAIN]).data for x in t.x[0]} == {"名目（帳簿）", "実質（調整後）"}
    assert "純資産は44.7百万円から52.7百万円" in _bs_caption(crisis, [GAIN, GAIN.model_copy(update={"id": "A9", "amount": 5_000})])
    assert "942.9億円は、調整を加えると336.9億円" in _bs_caption(alpha)
