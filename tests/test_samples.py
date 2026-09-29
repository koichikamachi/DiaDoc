"""同梱の見本データの形（公開版とテストが前提にする初期状態）を守る。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPANIES = sorted((ROOT / "data/companies").glob("C*"))


def test_each_sample_has_one_open_first_run():
    """画面で試したときにできた回次（第2次分析など）や凍結が、見本に紛れ込んでいないこと。"""
    for company in COMPANIES:
        runs = sorted(p for p in (company / "runs").iterdir() if (p / "run.json").exists())
        assert [r.name for r in runs] == ["run_001_initial"], company.name
        meta = json.loads((runs[0] / "run.json").read_text(encoding="utf-8"))
        assert meta["status"] == "open" and meta["frozen_at"] is None, company.name


def test_no_runtime_files_in_samples():
    names = ("checkpoints.sqlite", "debate_trace.jsonl", "adjustments.json")
    import subprocess

    tracked = subprocess.run(["git", "ls-files", "data"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert not [f for f in tracked if f.rsplit("/", 1)[-1].startswith(names)]
