"""論争を端末で1手ずつ進めて確かめるためのコマンド（画面の操作デッキができるまでの確認用）。

使い方（プロジェクトのルートで）:
    python scripts/debate_cli.py C002_sample_crisis            # 対話：Enter=1手進める、r=次のラウンドへ、a=最後まで、q=終了
    python scripts/debate_cli.py C002_sample_crisis --all      # 最後まで一気に進める
    python scripts/debate_cli.py C002_sample_crisis --reset    # その回次の論争を最初からやり直す

APIキーがあれば Gemini、なければ台本（モック）で動く。DBD_DEBATE=mock でキーがあっても台本に固定できる。
途中の状態は回次フォルダの checkpoints.sqlite に残り、次に起動したときは続きから進む。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.graph import DebateSession  # noqa: E402
from core.runs import latest_run  # noqa: E402

NAMES = {"radar": "Analyst Radar", "growth": "Prof. Growth", "rebuild": "Dr. Rebuild", "judge": "Moderator Judge",
         "human": "支援担当者"}


def show(msgs, s: DebateSession) -> None:
    st = s.state()
    verdict = {r.message_id: r.verdict for r in st.rulings}
    for m in msgs:
        print(f"\n■ 第{m.round}ラウンド［{m.phase}］ {NAMES.get(m.speaker, m.speaker)}（{m.action}）")
        print(m.text)
        if m.sources and m.speaker != "judge":
            print("  出典：" + "、".join(x.label() for x in m.sources))
        for b in m.bridges:
            print(f"  因果ブリッジ：{b.account} {b.direction} {b.amount:,} → 資金 {b.cf_effect:,}（{b.lead_months}か月後・"
                  f"{'毎年' if b.recurring else '一回'}）")
    for m in msgs:
        if m.speaker == "judge":
            ruled = [f"{x.id}={verdict.get(x.id, '—')}" for x in st.messages if x.round == m.round and x.speaker not in ("judge", "human")]
            print("  判定：" + "、".join(ruled))
    nxt = s.next_node
    print(f"\n―― 次：{NAMES.get(nxt, '（終了）') if nxt else '（終了。止まった理由：' + str(st.stop_reason) + '）'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="DiaDoc 論争のステップ実行")
    ap.add_argument("company")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    run = latest_run(a.company)
    if run is None:
        print(f"企業が見つかりません：{a.company}")
        return 2
    db = run.path / DebateSession.DB_NAME
    if a.reset and db.exists():
        if run.frozen:
            print("凍結済みの回次はやり直せません")
            return 2
        for p in run.path.glob(DebateSession.DB_NAME + "*"):
            p.unlink()
    s = DebateSession(run)
    print(f"{a.company}／{run.meta.label}　発言の生成：{s.speaker.name}")
    s.start()
    if a.all:
        while not s.finished:
            show(s.step(), s)
        return 0
    while not s.finished:
        cmd = input("\n[Enter]=1手 / r=ラウンド / a=最後まで / q=終了 > ").strip().lower()
        if cmd == "q":
            break
        if cmd == "a":
            while not s.finished:
                show(s.step(), s)
        elif cmd == "r":
            show(s.run_round(), s)
        else:
            show(s.step(), s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
