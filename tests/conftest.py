"""テスト共通の設定。

手元の .env に本物の API キーがあっても、テストが Gemini を呼ばない（課金・通信しない）ようにする。
Gemini 経路のテストは偽クライアントを明示的に渡して行う。
"""

import pytest


@pytest.fixture(autouse=True)
def _never_call_real_gemini(monkeypatch):
    monkeypatch.setenv("DBD_EXTRACTOR", "mock")
    monkeypatch.setenv("DBD_DEBATE", "mock")
