"""公開デモのセッション別作業場所（DBD_SESSION_SANDBOX=1）。本物の Gemini は呼ばない。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core import adjust, sandbox
from core.runs import data_dir, latest_run, seed_dir

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    seed = tmp_path / "seed"
    shutil.copytree(ROOT / "data", seed)
    # 見本に紛れ込んだ実行時ファイルは複製しない
    stray = seed / "companies/C002_sample_crisis/runs/run_001_initial/checkpoints.sqlite"
    stray.write_text("x")
    monkeypatch.setenv("DBD_DATA_DIR", str(seed))
    monkeypatch.setenv("DBD_SESSION_SANDBOX", "1")
    monkeypatch.setenv("DBD_SANDBOX_ROOT", str(tmp_path / "sandboxes"))
    return seed


def _as(sid):
    token = sandbox._SESSION.set(sid)
    return token


def test_each_session_gets_its_own_copy(demo):
    t = _as("aaa")
    a = data_dir()
    sandbox._SESSION.reset(t)
    t = _as("bbb")
    b = data_dir()
    sandbox._SESSION.reset(t)
    assert a != b and a.parent.parent == b.parent.parent
    assert seed_dir() == demo and (a / "companies/C002_sample_crisis").exists()
    assert not (a / "companies/C002_sample_crisis/runs/run_001_initial/checkpoints.sqlite").exists()


def test_writes_stay_in_the_session(demo):
    t = _as("aaa")
    run = latest_run("C002_sample_crisis")
    adjust.add(run, "仮払金", "その他の流動資産", -2300, "精算の見込みなし", "suspense")
    assert len(adjust.load(run)) == 1
    sandbox._SESSION.reset(t)
    t = _as("bbb")
    assert adjust.load(latest_run("C002_sample_crisis")) == []            # 別の審査員には見えない
    sandbox._SESSION.reset(t)
    assert not list(demo.rglob("adjustments.json"))                      # 見本は書き換えない


def test_without_a_session_falls_back_to_seed(demo):
    assert data_dir() == demo


def test_stale_sandboxes_are_pruned(demo, monkeypatch):
    t = _as("old")
    old = data_dir().parent
    sandbox._SESSION.reset(t)
    import os
    os.utime(old / ".touched", (1, 1))
    t = _as("new")
    data_dir()
    sandbox._SESSION.reset(t)
    assert not old.exists()


def test_read_only_seed_gives_a_writable_copy(demo):
    import os
    import stat

    for p in [demo, *demo.rglob("*")]:
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        t = _as("ro")
        run = latest_run("C002_sample_crisis")
        adjust.add(run, "仮払金", "その他の流動資産", -100)
        assert os.access(run.path, os.W_OK)
        sandbox._SESSION.reset(t)
    finally:
        for p in [demo, *demo.rglob("*")]:
            p.chmod(p.stat().st_mode | stat.S_IWUSR)


def test_bundled_file_names_are_ascii():
    """Cloud Run は日本語のファイル名を含むイメージを読み込めない。表示名は inputs/titles.json に持たせる。"""
    bad = [str(p.relative_to(ROOT)) for base in ("data", "src", ".streamlit") for p in (ROOT / base).rglob("*")
           if "__pycache__" not in p.parts and not p.name.isascii()]
    assert bad == []


def test_titles_give_japanese_source_names():
    from agents.base import DebateContext
    from core import digest
    from core.runs import Run

    run = Run("C002_sample_crisis", "run_001_initial")
    ctx = DebateContext.from_run(run)
    assert "ヒアリングメモ_第62期（架空）" in ctx.materials and "ヒアリングメモ_第62期（架空）" in ctx.registry
    names = [d.name for d in digest.documents(run, ctx)]
    assert "ヒアリングメモ_第62期（架空）" in names and "titles" not in names
