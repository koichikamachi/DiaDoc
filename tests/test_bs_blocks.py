"""比例縮尺の貸借対照表（metrics.bs_blocks）とその説明文。"""

from __future__ import annotations

import pytest

from core import metrics
from core.runs import latest_run


@pytest.fixture(scope="module")
def alpha():
    return latest_run("C001_sample_alpha").financials()


@pytest.fixture(scope="module")
def crisis():
    return latest_run("C002_sample_crisis").financials()


@pytest.mark.parametrize("mode", ["nominal", "real"])
@pytest.mark.parametrize("name", ["alpha", "crisis"])
def test_blocks_add_up_to_the_balance_sheet(request, name, mode):
    fin = request.getfixturevalue(name)
    blocks, bs = metrics.bs_blocks(fin, mode), metrics.balance_sheet(fin, mode)
    assets = sum(b.amount for b in blocks if b.side == "資産")
    claims = sum(b.amount for b in blocks if b.side == "負債・純資産")
    assert assets == bs["総資産"]
    assert abs(claims - (bs["負債"] + bs["純資産"])) <= 2      # 原資料の千円未満切捨てによる差だけ


def test_nominal_separates_what_the_real_view_removes(alpha):
    nom = metrics.bs_blocks(alpha, "nominal")
    gain = [b for b in nom if b.gain_related]
    assert {b.label for b in gain} == {"株式の含み益", "繰延税金負債", "評価差額金"}
    assert not any(b.gain_related for b in metrics.bs_blocks(alpha, "real"))
    # 含み益以外の区画の合計は名目と実質でほぼ同じ（差は相殺されていた繰延税金資産の戻しだけ）
    rest = sum(b.amount for b in nom if b.side == "資産" and not b.gain_related)
    dta = alpha.supplementary["dta_netted"].cur
    assert metrics.balance_sheet(alpha, "real")["総資産"] == rest + dta


def test_crisis_has_no_gain_blocks_and_same_views(crisis):
    assert metrics.bs_blocks(crisis, "nominal") == metrics.bs_blocks(crisis, "real")
    assert not any(b.gain_related for b in metrics.bs_blocks(crisis, "nominal"))


def test_watch_items_only_for_present_accounts(alpha, crisis):
    assert metrics.watch_items(alpha) == []
    labels = [w[0] for w in metrics.watch_items(crisis)]
    assert labels == ["仮払金", "役員借入金", "保険積立金"]


def test_caption_wording(alpha, crisis):
    from ui.components.matrix import _bs_caption, _bs_chart

    assert _bs_caption(crisis).startswith("株式の含み益はありません")
    assert "約0%" not in _bs_caption(crisis)
    cap = _bs_caption(alpha)
    assert "株式の含み益が595.0億円（65%）" in cap and "実質の総資産は327.1億円" in cap
    assert {x for t in _bs_chart(crisis).data for x in t.x[0]} == {"名目＝実質"}
    assert {x for t in _bs_chart(alpha).data for x in t.x[0]} == {"名目", "実質"}
