"""環境変数とシステム定数。

GEMINI_API_KEY  … Gemini API キー（なければ GOOGLE_API_KEY）。どちらもなければファイル読み取りはモック動作になる
GEMINI_MODEL    … 読み取りに使うモデル。既定は gemini-3.8-flash（2026年9月時点の安定版 Flash）
DBD_DEBATE      … mock にすると、キーがあっても論争を台本（モック）で動かす
DBD_DATA_DIR    … data/ の場所（テストや Cloud Run で差し替える）
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# プロジェクト直下の .env を読み込む（既に設定済みの環境変数は上書きしない。Cloud Run ではシークレットが優先される）
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:  # python-dotenv がなくても、環境変数が直接設定されていれば動く
    pass

APP_NAME = "DiaDoc（ディアドック） | Dialectic-BizDoctor"
APP_SHORT = "DiaDoc"
APP_TAGLINE = "対立仮説検証による自律型経営診断システム"

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


def gemini_api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return key.strip() if key and key.strip() else None


def gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL


def extractor_mode() -> str:
    """"gemini" か "mock"。DBD_EXTRACTOR=mock でキーがあってもモックに固定できる。"""
    if os.environ.get("DBD_EXTRACTOR", "").lower() == "mock":
        return "mock"
    return "gemini" if gemini_api_key() else "mock"


def mock_reason() -> str:
    """読み取りがモックになっている理由（画面の説明用）。"""
    if os.environ.get("DBD_EXTRACTOR", "").lower() == "mock":
        return "環境変数 DBD_EXTRACTOR=mock で固定"
    return "GEMINI_API_KEY 未設定" if not gemini_api_key() else "モック指定"


def debate_mode() -> str:
    """"gemini" か "mock"。DBD_DEBATE=mock で論争だけを台本動作に固定できる。"""
    if os.environ.get("DBD_DEBATE", "").lower() == "mock":
        return "mock"
    return "gemini" if gemini_api_key() else "mock"
