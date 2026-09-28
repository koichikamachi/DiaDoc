"""公開デモ用：ブラウザのセッションごとの作業場所（DBD_SESSION_SANDBOX=1 のときだけ使う）。

見本（seed）の data/ を、セッションごとに一時フォルダへ複製する。論争の途中状態（checkpoints.sqlite）、
投入資料、実質化の調整はすべてこの複製に書かれ、見本そのものは書き換えない。
Cloud Run のファイルは一時的なので、コンテナが止まれば複製も消える。長く放置された複製は、
新しいセッションを作るときに片付ける。
"""

from __future__ import annotations

import contextvars
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

# LangGraph が別スレッドで処理を走らせても同じ作業場所を使えるよう、セッションIDを文脈にも持たせる
_SESSION: contextvars.ContextVar[str | None] = contextvars.ContextVar("dbd_session", default=None)
_LOCK = threading.Lock()
TTL_SECONDS = 6 * 3600          # これより長く使われていない複製は片付ける
RUNTIME_FILES = ("checkpoints.sqlite*", "debate_trace.jsonl", "adjustments.json", "*.tmp")


def root() -> Path:
    return Path(os.environ.get("DBD_SANDBOX_ROOT", tempfile.gettempdir())) / "dbd-sessions"


def _streamlit_session_id() -> str | None:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx(suppress_warning=True)
    except Exception:
        return None
    return ctx.session_id if ctx else None


def current_session_id() -> str | None:
    sid = _streamlit_session_id()
    if sid:
        _SESSION.set(sid)
        return sid
    return _SESSION.get()


def _prune(now: float) -> None:
    base = root()
    if not base.exists():
        return
    for d in base.iterdir():
        try:
            if now - (d / ".touched").stat().st_mtime > TTL_SECONDS:
                shutil.rmtree(d, ignore_errors=True)
        except FileNotFoundError:
            shutil.rmtree(d, ignore_errors=True)


def _make_writable(path: Path) -> None:
    for p in [path, *path.rglob("*")]:
        p.chmod(0o755 if p.is_dir() else 0o644)


def session_data_dir(seed: Path, session_id: str | None = None) -> Path | None:
    """このセッションの data/。初めて呼ばれたときに見本を複製する。セッションが分からなければ None。"""
    sid = session_id or current_session_id()
    if not sid:
        return None
    safe = "".join(c for c in sid if c.isalnum() or c in "-_")[:64]
    home = root() / safe
    data = home / "data"
    if not data.exists():
        with _LOCK:
            if not data.exists():
                now = time.time()
                _prune(now)
                tmp = home / "data.partial"
                shutil.rmtree(tmp, ignore_errors=True)
                shutil.copytree(seed, tmp, ignore=shutil.ignore_patterns(*RUNTIME_FILES),
                                copy_function=shutil.copyfile)
                _make_writable(tmp)          # 見本が読み取り専用でも、複製には書き込めるようにする
                tmp.replace(data)
    touched = home / ".touched"
    try:
        if not touched.exists() or time.time() - touched.stat().st_mtime > 60:
            touched.touch()
    except OSError:
        pass
    return data
