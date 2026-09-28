"""読み取りの実証テスト用コマンド。data/ には何も書かない。

使い方（プロジェクトのルートで）:
    python src/tools/ingest_cli.py <資料のパス> [--compare] [--save 結果.json]

    --compare  読み取った数値を、手作業で検算済みの制作サンプル（第1次分析）と1科目ずつ突き合わせる
    --save     読み取り結果（標準科目・出典頁・検算結果）をJSONで保存する
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import config  # noqa: E402
from schema import Financials  # noqa: E402
from tools.file_ingest import SAMPLE_FINANCIALS, get_extractor, ingest  # noqa: E402


def compare(read: Financials, truth: Financials) -> tuple[int, int, list[str], list[str]]:
    """（一致件数、比較件数、食い違い、読み取れなかった科目）を返す。"""
    same, total, diffs, missing = 0, 0, [], []
    for key, t in truth.items.items():
        r = read.items.get(key)
        for period in ("prev", "cur"):
            tv = getattr(t, period)
            if tv is None:
                continue
            total += 1
            rv = None if r is None else getattr(r, period)
            if rv is None:
                missing.append(f"{t.label}（{'前期' if period == 'prev' else '当期'}）")
            elif rv == tv:
                same += 1
            else:
                diffs.append(f"{t.label}（{'前期' if period == 'prev' else '当期'}）：読取 {rv:,}／正解 {tv:,}　p.{r.source.page}")
    return same, total, diffs, missing


def main() -> int:
    ap = argparse.ArgumentParser(description="DiaDoc 読み取り実証テスト")
    ap.add_argument("path")
    ap.add_argument("--compare", action="store_true", help="制作サンプル（検算済み）と突き合わせる")
    ap.add_argument("--save", help="結果をJSONで保存するパス")
    a = ap.parse_args()

    path = Path(a.path)
    if not path.exists():
        print(f"ファイルが見つかりません：{path}")
        return 2
    ex = get_extractor()
    print(f"読み取りエンジン：{ex.name}" + ("（モック動作。APIキー未設定か DBD_EXTRACTOR=mock。ファイルは読みません）" if ex.name == "mock" else ""))
    print(f"資料：{path.name}（{path.stat().st_size / 1024:,.0f}KB）　読み取り中…")
    t0 = time.time()
    out = ingest(path.name, path.read_bytes(), "CLI", ex)
    print(f"所要時間：{time.time() - t0:,.1f}秒")
    print()
    print(out.summary())
    r = out.report
    print(f"資料の種別：{r.document_type}　単位：{r.unit}　端数処理：{r.rounding}")
    for title, rows in (("別名を吸収", r.remapped), ("未確認（null）", r.unverified), ("除外", r.dropped),
                        ("重複", r.duplicates), ("判読不能", r.unreadable), ("注意", r.warnings)):
        if rows:
            print(f"\n{title}（{len(rows)}件）")
            for x in rows[:30]:
                print(f"  - {x}")
    if out.reconciliation is not None:
        bad = [c for c in out.reconciliation.checks if c.status != "一致"]
        if bad:
            print(f"\n検算で一致しなかった項目（{len(bad)}件）")
            for c in bad:
                ds = "、".join(f"{p.period}:差{p.diff}（許容{p.tolerance}）" for p in c.periods)
                print(f"  - {c.group}／{c.name}　{c.status}　{ds}")

    print("\nデータ請求に関わる科目（R1 広告宣伝費・R2 販売促進費・R4 仮払金等）")
    for key in ("sga_adv", "sga_promo", "suspense", "other_recv"):
        it = out.financials.items.get(key)
        if it is None:
            print(f"  - {key}：資料に記載なし（読み取り対象の行なし）")
        else:
            v = "未確認" if it.cur is None else f"{it.cur:,}"
            print(f"  - {it.label}：当期 {v}（{it.source_label}、p.{it.source.page or '？'}）")

    if a.compare:
        truth = Financials.model_validate(json.loads(SAMPLE_FINANCIALS.read_text(encoding="utf-8")))
        same, total, diffs, missing = compare(out.financials, truth)
        print(f"\n制作サンプルとの突き合わせ：{total}件中 一致{same}件、食い違い{len(diffs)}件、読み取りなし{len(missing)}件")
        for x in diffs:
            print(f"  ✗ {x}")
        if missing:
            print("  読み取りなし：" + "、".join(missing[:40]) + ("…" if len(missing) > 40 else ""))

    if a.save:
        Path(a.save).write_text(out.model_dump_json(indent=1), encoding="utf-8")
        print(f"\n保存しました：{a.save}")
    return 0 if out.gate != "停止" else 1


if __name__ == "__main__":
    raise SystemExit(main())
