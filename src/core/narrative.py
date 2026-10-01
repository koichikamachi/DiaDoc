"""診断経緯の文章化（ナラティブレポート）。構造化した診断レポート（Markdown）を材料に、LLM で報告書の文章を書く。

二部構成：
- 第1部：第N次経営診断 審理経緯レポート（社内・監査向け。である調）
- 第2部：金融機関提出用 経営診断サマリー（です・ます調）

守ること（CLAUDE.md 6.1 根拠がなければ止まる）：
- 材料は、論争が終わった回次の構造化レポートだけ。数字・事実・判定はそこから取り、足さない。
  記録にないもの（銀行名、人名、日付、今後の数値計画など）は書かせず「（記録なし）」とさせる
- 判定と結論はプログラムが出したものをそのまま使う。文章化で結論を変えない
- 生成した文章の数字を、材料のレポートと突き合わせる。材料にない数字は「要確認」として一覧で添える
- 材料のレポートには発言や資料の文面が含まれるので、指示としてではなくデータとして渡す（core.untrusted）
- 生成した文章は下書きである。提出の前に人が読んで直す（画面とファイルの冒頭に明記する）

API キーがないとき・テスト（DBD_DEBATE=mock）は、構造化レポートの要点を見出しの下に並べたモックの下書きを返す。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

import config

FILE_MD = "narrative.md"
FILE_META = "narrative.json"
PART1 = "第1部：第{n}次経営診断 審理経緯レポート"
PART2 = "第2部：金融機関提出用 経営診断サマリー"
PART1_SECTIONS = ("1. 現状把握と資産実質化", "2. 資金不足額の確定", "3. 改善策を巡る攻防と判定", "4. 最終結論と定量的根拠")
PART2_SECTIONS = ("基本方針と診断概要", "実質財務状態と資産保全性（B/S）", "現状の資金収支と返済能力分析（P/L・C/F）",
                  "経営改善施策と資金繰り改善効果", "金融機関へのお願い")
DRAFT_NOTE = ("※ この文章は DiaDoc が診断記録をもとに生成した下書きです。数字と判定は記録どおりですが、"
              "提出の前に必ず人が読み、事実と表現を確かめてください。")


@dataclass
class Narrative:
    text: str
    engine: str                     # 例：gemini:gemini-3.8-flash／mock
    generated_at: str
    report_hash: str                # 材料にした構造化レポートの指紋（同じ材料なら作り直さない）
    unverified_numbers: list[str] = field(default_factory=list)   # 材料のレポートにない数字

    def document(self) -> str:
        """保存・ダウンロード用の本文（下書きの注意と照合結果を添える）。"""
        tail = ["", "---", f"生成：{self.engine}　{self.generated_at}　材料：構造化診断レポート（指紋 {self.report_hash}）"]
        if self.unverified_numbers:
            tail.append("数字の照合：材料のレポートにない数字があります（要確認）："
                        + "、".join(self.unverified_numbers))
        else:
            tail.append("数字の照合：本文の数字はすべて材料のレポートにあります")
        return f"{DRAFT_NOTE}\n\n{self.text.strip()}\n" + "\n".join(tail) + "\n"


def run_number(run) -> str:
    m = re.search(r"第(\d+)次", run.meta.label)
    return m.group(1) if m else str(run.meta.seq)


def report_hash(report: str) -> str:
    return hashlib.sha256(report.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# 指示文
# ---------------------------------------------------------------------------
def system_prompt(n: str) -> str:
    from core.untrusted import GUARD

    p1 = "\n".join(f"## {s}" for s in PART1_SECTIONS)
    p2 = "\n".join(f"## {s}" for s in PART2_SECTIONS)
    return f"""あなたは、中小企業の経営診断と事業再生の実務に通じた公認会計士です。
経営診断システム DiaDoc が一つの分析回次を終えた記録（構造化診断レポート）をもとに、報告書の文章を書きます。

# 厳守すること
- 数字・事実・判定は、構造化診断レポートに書かれたものだけを使う。記録にない数字・銀行名・人名・日付・計画値を作らない。
  書くべき事柄が記録にないときは「（記録なし）」と書く
- 数字を組み合わせて示すときは、式を書く（例：継続改善CF 年1,500千円 ≧ 必要CF 年1,370千円）。金額の単位は千円
- 判定（通過・差し戻し・減額採択・結論フェーズ）はプログラムが出したものであり、言い換えても結論を変えない。
  診断が「充足決着」でないときは、そのことを正直に書く（資金繰りが改善したかのように書かない）
- Moderator Judge の総括は LLM による論点整理である。引くときは「審判の総括によれば」と出どころを示す
- 登場人物の呼び方：Analyst Radar（調査）、Prof. Growth（成長・現場の立場）、Dr. Rebuild（財務規律の立場）、
  Moderator Judge（審判）、ライム（人間の診断担当者。介入と確定判断を行うことがある）
- 記録にない出来事を書かない。介入・確定・調整が記録に「なし」「未確定」なら、行われなかったと一言書くだけにし、
  「介入を確認したところ」のように、行われたかのような書き方をしない
- {GUARD}

# 書く形（Markdown。見出しの文言と順序を変えない）
# {PART1.format(n=n)}
（社内・監査向け。である調。議論の経緯と、どこで何が決まったかを時系列で書く）
{p1}

# {PART2}
（金融機関の担当者向け。です・ます調。簡潔に。専門用語には短い補いを添える）
{p2}

# 各節の中身
- 第1部 1：第1ラウンドで示された事実と、人間の介入による実質化の調整（時価調整。根拠と金額。記録が「なし」なら「調整なし」とだけ書く）
- 第1部 2：約定返済額が書類から確かめられたか、返済予定表で確定したか（確定値・根拠）と、それによって必要CFがいくらに定まったか。これが診断の分岐点である
- 第1部 3：Prof. Growth の提案、Dr. Rebuild の反論、審判の判定（通過・差し戻し・減額採択とその理由）
- 第1部 4：結論フェーズと、その定量的根拠（式で）。残された課題（未着手のレバー、未解決の宿題、計算上の留保）
- 第2部「金融機関へのお願い」：記録と結論に合う範囲で、約定返済の履行見通しと、短期借入金がある場合はその折り返し（借り換え）継続への支援を依頼する。
  結論が充足決着でない場合は、何が未確定で、何の資料をいつまでに示すか（宿題）を添え、根拠のない約束はしない
"""


def user_prompt(report: str) -> str:
    from core.untrusted import wrap

    return ("次の構造化診断レポートをもとに、指定の二部構成で報告書を書いてください。\n\n"
            + wrap("構造化診断レポート", report))


# ---------------------------------------------------------------------------
# 数字の照合
# ---------------------------------------------------------------------------
_NUM = re.compile(r"(?<![\d,.])[△▲\-−]?\d{1,3}(?:,\d{3})+(?![\d,])|(?<![\d,.])[△▲\-−]?\d{3,}(?![\d,])")


def _norm(tok: str) -> str:
    return tok.replace(",", "").lstrip("△▲-−")


def numbers_in(text: str) -> set[str]:
    return {_norm(t) for t in _NUM.findall(text or "")}


def unverified_numbers(text: str, report: str) -> list[str]:
    """本文にあって、材料のレポートにない数字（3桁以上。カンマや△の違いは同じとみなす）。"""
    known = numbers_in(report)
    out: list[str] = []
    for t in _NUM.findall(text or ""):
        if _norm(t) not in known and t not in out:
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------
class GeminiWriter:
    def __init__(self, client=None, model: str | None = None, temperature: float = 0.3):
        if client is None:
            from google import genai

            client = genai.Client(api_key=config.gemini_api_key())
        self.client = client
        self.model = model or config.gemini_model()
        self.temperature = temperature
        self.name = f"gemini:{self.model}"

    def write(self, system: str, user: str) -> str:
        from google.genai import types

        last = None
        for _ in range(2):   # 空の返答だけは一度だけ作り直す
            resp = self.client.models.generate_content(
                model=self.model, contents=user,
                config=types.GenerateContentConfig(system_instruction=system, temperature=self.temperature))
            text = (getattr(resp, "text", None) or "").strip()
            if text:
                return text
            last = "Gemini の返答が空でした"
        raise RuntimeError(last)


class MockWriter:
    """API キーがないとき・テスト用。構造化レポートの行を、決まった見出しの下に並べるだけ（文章は作らない）。"""

    name = "mock"

    def write(self, system: str, user: str) -> str:
        report = re.sub(r"</?untrusted_document[^>]*>", "", user.split("\n\n", 1)[-1])
        sec = _sections(report)
        n = re.search(r"# 第1部：第(\d+)次", system)
        n = n.group(1) if n else "1"

        def pick(*names: str) -> str:
            lines = [ln for k in names for ln in sec.get(k, []) if ln.strip()]
            return "\n".join(lines[:12]) or "（記録なし）"

        body = [f"# {PART1.format(n=n)}", "（モック：Gemini を使わず、構造化レポートの行を見出しの下に並べた下書きです）", ""]
        mapping1 = {PART1_SECTIONS[0]: ("2. 前提条件と監査的オーバーライド（人間介入）",),
                    PART1_SECTIONS[1]: ("1. エグゼクティブサマリー",),
                    PART1_SECTIONS[2]: ("3. 採択された改善シナリオ一覧", "4. 残されたリスク・未決争点"),
                    PART1_SECTIONS[3]: ("1. エグゼクティブサマリー", "5. データ請求（宿題リスト）")}
        for h, src in mapping1.items():
            body += [f"## {h}", pick(*src), ""]
        body += [f"# {PART2}", ""]
        mapping2 = {PART2_SECTIONS[0]: ("_head",), PART2_SECTIONS[1]: ("2. 前提条件と監査的オーバーライド（人間介入）",),
                    PART2_SECTIONS[2]: ("1. エグゼクティブサマリー",), PART2_SECTIONS[3]: ("3. 採択された改善シナリオ一覧",),
                    PART2_SECTIONS[4]: ("5. データ請求（宿題リスト）",)}
        for h, src in mapping2.items():
            body += [f"## {h}", pick(*src), ""]
        return "\n".join(body)


def _sections(report: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"_head": []}
    cur = "_head"
    for ln in report.splitlines():
        if ln.startswith("## "):
            cur = ln[3:].strip()
            out[cur] = []
        elif not ln.startswith("# "):
            out.setdefault(cur, []).append(ln)
    return out


def default_writer():
    return GeminiWriter() if config.debate_mode() == "gemini" else MockWriter()


def generate(run, writer=None, report: str | None = None) -> Narrative:
    """論争が終わった回次について、報告書の文章を作る。終わっていなければ ValueError。"""
    from core.conclusion import finished, report_markdown
    from core.digest import load_state

    if not finished(load_state(run)):
        raise ValueError("診断経緯の文章化は、論争が終わった（診断完了の）回次でだけ行えます")
    report = report if report is not None else report_markdown(run)
    writer = writer or default_writer()
    text = writer.write(system_prompt(run_number(run)), user_prompt(report))
    nar = Narrative(text=text, engine=writer.name, generated_at=datetime.now().isoformat(timespec="seconds"),
                    report_hash=report_hash(report), unverified_numbers=unverified_numbers(text, report))
    save(run, nar)
    return nar


def save(run, nar: Narrative) -> None:
    """回次に保存する（凍結した回次には書かない）。生成したことを監査証跡に残す。"""
    if run.frozen:
        return
    run.write_text(FILE_MD, nar.document())
    run.write(FILE_META, {"engine": nar.engine, "generated_at": nar.generated_at, "report_hash": nar.report_hash,
                          "unverified_numbers": nar.unverified_numbers, "text": nar.text})
    run.write("audit_log.json", run.read("audit_log.json", []) + [
        {"at": nar.generated_at, "actor": "システム（文章化）", "action": "診断経緯の文章化（下書きを生成）",
         "entries": [f"生成：{nar.engine}", f"材料のレポートの指紋：{nar.report_hash}",
                     f"材料にない数字：{len(nar.unverified_numbers)}件"]}])


def load(run) -> Narrative | None:
    m = run.read(FILE_META)
    if not m or "text" not in m:
        return None
    return Narrative(text=m["text"], engine=m.get("engine", ""), generated_at=m.get("generated_at", ""),
                     report_hash=m.get("report_hash", ""), unverified_numbers=m.get("unverified_numbers", []))
