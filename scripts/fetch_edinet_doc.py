"""EDINET API v2 から書類を取得する小さなスクリプト（DiaDoc 本体とは独立）。

キーは src.config と同じく .env の EDINET_API_KEY から読む。キーの値は出力しない。

使い方:
  python scripts/fetch_edinet_doc.py list 2026-09-30 [--sec 65940] [--name ニデック]
  python scripts/fetch_edinet_doc.py get <docID> <保存先フォルダ>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import config  # noqa: E402,F401  （.env の読み込み）

BASE = "https://api.edinet-fsa.go.jp/api/v2"
TYPES = {1: "_xbrl.zip", 2: ".pdf", 5: "_csv.zip"}


def _key() -> str:
    key = os.environ.get("EDINET_API_KEY", "").strip()
    if not key:
        sys.exit("EDINET_API_KEY が設定されていません（.env を確認）")
    return key


def _get(url: str, params: dict) -> requests.Response:
    key = _key()
    try:
        return requests.get(url, params={**params, "Subscription-Key": key}, timeout=120)
    except requests.RequestException as e:  # 例外文にURL（キー入り）が含まれうるので伏せる
        sys.exit(f"通信エラー: {str(e).replace(key, '***')}")


def list_docs(date: str, sec: str | None, name: str | None) -> list[dict]:
    r = _get(f"{BASE}/documents.json", {"date": date, "type": 2})
    data = r.json()
    meta = data.get("metadata", {})
    if str(meta.get("status")) != "200":
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return []
    hits = []
    for d in data.get("results", []):
        if (sec and d.get("secCode") == sec) or (name and name in (d.get("filerName") or "")):
            hits.append(d)
    return hits


def get_doc(doc_id: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for t, suffix in TYPES.items():
        r = _get(f"{BASE}/documents/{doc_id}", {"type": t})
        ctype = r.headers.get("Content-Type", "")
        if r.status_code != 200 or "json" in ctype:
            print(f"type={t}: 保存しない（HTTP {r.status_code}, {ctype}）")
            print(r.text[:2000])
            continue
        path = out_dir / f"{doc_id}{suffix}"
        path.write_bytes(r.content)
        print(f"type={t}: {path.name} {len(r.content):,} bytes")
        if suffix.endswith(".zip"):
            dest = out_dir / path.stem
            with zipfile.ZipFile(path) as z:
                z.extractall(dest)
            print(f"  展開: {dest.name}/ （{len(z.namelist())} ファイル）")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list")
    pl.add_argument("date")
    pl.add_argument("--sec")
    pl.add_argument("--name")
    pg = sub.add_parser("get")
    pg.add_argument("doc_id")
    pg.add_argument("out_dir")
    a = p.parse_args()
    if a.cmd == "list":
        keys = ["docID", "edinetCode", "secCode", "filerName", "docTypeCode", "docDescription",
                "submitDateTime", "periodStart", "periodEnd", "withdrawalStatus", "parentDocID"]
        hits = list_docs(a.date, a.sec, a.name)
        print(json.dumps([{k: d.get(k) for k in keys} for d in hits], ensure_ascii=False, indent=2))
    else:
        get_doc(a.doc_id, Path(a.out_dir))


if __name__ == "__main__":
    main()
