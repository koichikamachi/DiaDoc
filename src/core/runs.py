"""企業と分析回次（Run）の保管庫。

原則（CLAUDE.md・data/ 構成）:
- 過去の回次は凍結（frozen）し、以後いっさい書き換えない。書き込みを試みると FrozenRunError。
- 投入資料は上書きしない。同名ファイルは番号を付けて別名で保存する。
- 新しい回次は、前の回次の状態（ツリー・データ請求・制約）を複製して始め、前の回次は凍結する。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from schema import Financials, RunMeta

ROOT = Path(__file__).resolve().parents[2]


def seed_dir() -> Path:
    """同梱の data/（見本の初期状態）。DBD_DATA_DIR で差し替えられる。"""
    return Path(os.environ.get("DBD_DATA_DIR", ROOT / "data"))


def data_dir() -> Path:
    """いま使う data/。

    DBD_SESSION_SANDBOX=1（公開デモ）のときは、ブラウザのセッションごとに見本を複製した専用の作業場所を返す。
    審査員が何人同時に開いても、互いの論争・資料・調整（と SQLite の途中状態）は混ざらず、
    どのセッションも C001・C002 の見本の初期状態から始まる。コンテナが止まればすべて消える。
    """
    if os.environ.get("DBD_SESSION_SANDBOX") == "1":
        from core import sandbox

        d = sandbox.session_data_dir(seed_dir())
        if d is not None:
            return d
    return seed_dir()


class FrozenRunError(RuntimeError):
    """凍結済みの回次に書き込もうとした。"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# 企業
# ---------------------------------------------------------------------------
def list_companies() -> list[dict]:
    base = data_dir() / "companies"
    out = []
    for d in sorted(base.glob("*")) if base.exists() else []:
        meta = _read_json(d / "meta.json")
        if meta:
            meta["dir"] = d.name
            out.append(meta)
    return out


def company_dir(company: str) -> Path:
    return data_dir() / "companies" / company


def load_benchmarks(company: str) -> dict:
    """企業が参照するベンチマーク（業界平均・比較企業）を読み込む。"""
    conf = _read_json(company_dir(company) / "benchmarks.json", {}) or {}
    base = data_dir() / "benchmarks"
    out = {"industry": None, "peers": []}
    if conf.get("industry"):
        out["industry"] = _read_json(base / "industries" / conf["industry"])
    for p in conf.get("peers", []):
        d = _read_json(base / "peers" / p)
        if d:
            out["peers"].append(d)
    return out


# ---------------------------------------------------------------------------
# 回次
# ---------------------------------------------------------------------------
class Run:
    def __init__(self, company: str, run_id: str):
        self.company = company
        self.run_id = run_id
        self.path = company_dir(company) / "runs" / run_id

    # --- メタ情報 ----------------------------------------------------------
    @property
    def meta(self) -> RunMeta:
        return RunMeta.model_validate(_read_json(self.path / "run.json"))

    @property
    def frozen(self) -> bool:
        return self.meta.status == "frozen"

    def _guard(self) -> None:
        if self.frozen:
            raise FrozenRunError(f"{self.run_id} は凍結済みです。書き換えはできません")

    # --- 読み出し -----------------------------------------------------------
    def read(self, name: str, default=None):
        return _read_json(self.path / name, default)

    def read_text(self, name: str) -> str | None:
        p = self.path / name
        return p.read_text(encoding="utf-8") if p.exists() else None

    def inputs(self) -> list[Path]:
        d = self.path / "inputs"
        return sorted(p for p in d.glob("*") if p.is_file()) if d.exists() else []

    # --- 書き込み（開いている回次のみ） --------------------------------------
    def write(self, name: str, data) -> None:
        self._guard()
        _write_json(self.path / name, data)

    def write_text(self, name: str, text: str) -> None:
        self._guard()
        p = self.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def save_input(self, filename: str, content: bytes) -> Path:
        """投入資料を inputs/ に保存する。同名があれば番号を付け、既存ファイルは上書きしない。"""
        self._guard()
        d = self.path / "inputs"
        d.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|]', "_", Path(filename).name) or "upload"
        target = d / safe
        stem, suffix, i = target.stem, target.suffix, 2
        while target.exists():
            target = d / f"{stem}_{i}{suffix}"
            i += 1
        with open(target, "xb") as f:  # "x" は既存ファイルがあれば失敗する
            f.write(content)
        return target

    def freeze(self) -> None:
        if self.frozen:
            return
        meta = self.meta
        meta.status = "frozen"
        meta.frozen_at = now_iso()
        _write_json(self.path / "run.json", meta.model_dump())

    # --- 財務データ（なければ親の回次から引き継ぐ） -----------------------------
    def financials_source(self) -> "Run | None":
        run: Run | None = self
        while run is not None:
            if (run.path / "inputs" / "financials.json").exists():
                return run
            parent = run.meta.parent
            run = Run(self.company, parent) if parent else None
        return None

    def financials(self) -> Financials | None:
        src = self.financials_source()
        if src is None:
            return None
        return Financials.model_validate(_read_json(src.path / "inputs" / "financials.json"))

    def parent(self) -> "Run | None":
        return Run(self.company, self.meta.parent) if self.meta.parent else None


def list_runs(company: str) -> list[Run]:
    d = company_dir(company) / "runs"
    runs = [Run(company, p.name) for p in d.glob("run_*") if (p / "run.json").exists()] if d.exists() else []
    return sorted(runs, key=lambda r: r.meta.seq)


def latest_run(company: str) -> Run | None:
    runs = list_runs(company)
    return runs[-1] if runs else None


CARRY_OVER = ("decision_tree.json", "data_requests.json", "constraints.json")


def start_next_run(company: str, trigger: str) -> Run:
    """最新の回次を凍結し、その状態を引き継いだ次の回次を開く。"""
    prev = latest_run(company)
    if prev is None:
        raise RuntimeError("最初の回次がありません")
    seq = prev.meta.seq + 1
    run_id = f"run_{seq:03d}_followup"
    run = Run(company, run_id)
    if run.path.exists():
        raise FileExistsError(f"{run_id} は既に存在します")
    today = datetime.now()
    meta = RunMeta(run_id=run_id, seq=seq, label=f"第{seq}次分析", as_of=today.strftime("%Y/%m/%d"),
                   status="open", parent=prev.run_id, created_at=now_iso(), trigger=trigger)
    _write_json(run.path / "run.json", meta.model_dump())
    (run.path / "inputs").mkdir(parents=True, exist_ok=True)
    for name in CARRY_OVER:
        data = prev.read(name)
        if data is not None:
            _write_json(run.path / name, data)
    _write_json(run.path / "debate_log.json", [])
    prev.freeze()
    return run


def _safe_name(name: str) -> str:
    """フォルダ名に使えない文字を除く（日本語はそのまま使う）。"""
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", (name or "").strip()).strip("._")
    return s[:40] or "company"


def create_company(name: str, industry: str = "", fictional: bool = False, mission: str = "") -> str:
    """新しい対象会社を作る。第1次分析（未開始・財務データなし）を用意し、会社のフォルダ名を返す。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("会社名を入れてください")
    base = data_dir() / "companies"
    base.mkdir(parents=True, exist_ok=True)
    nums = [int(m.group(1)) for d in base.iterdir() if d.is_dir() and (m := re.match(r"C(\d{3})", d.name))]
    n = max(nums, default=0) + 1
    company = f"C{n:03d}_{_safe_name(name)}"
    d = base / company
    if d.exists():
        raise FileExistsError(f"{company} は既にあります")
    display = f"C{n:03d}_{name}" + ("（架空モデル）" if fictional else "")
    _write_json(d / "meta.json", {
        "company_id": f"C{n:03d}", "name": name, "display_name": display, "industry": industry.strip(),
        "fictional": bool(fictional), "listed": False, "mission": mission.strip(),
        "note": "画面から新規作成。財務書類を投入すると第1次分析の財務データになる", "created_at": now_iso(),
    })
    _write_json(d / "benchmarks.json", {"industry": None, "peers": []})
    run = Run(company, "run_001_initial")
    meta = RunMeta(run_id="run_001_initial", seq=1, label="第1次分析", as_of=datetime.now().strftime("%Y/%m/%d"),
                   status="open", parent=None, created_at=now_iso(), trigger="新規作成（財務書類の投入待ち）")
    _write_json(run.path / "run.json", meta.model_dump())
    (run.path / "inputs").mkdir(parents=True, exist_ok=True)
    _write_json(run.path / "debate_log.json", [])
    _write_json(run.path / "data_requests.json", [])
    _write_json(run.path / "constraints.json", {"constraints": [], "stops": []})
    return company
