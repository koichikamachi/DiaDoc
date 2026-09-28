"""出典の照合（形式審査の一段）。発言に出てくる数字が、引用した頁に本当にあるかを確かめる。

形式審査は「出典の資料名と頁が、引用できる資料にあるか」までしか見ていなかった。ここでは一歩進めて、
発言の中の金額・割合が、引用した頁に書かれているかを照らし合わせる。

取り違えと判定するのは、次の場合だけにとどめる（正しい発言を差し戻さないため）。
- 数字が、引用したどの頁にもない
- しかも、同じ数字が引用できる資料の別の頁にある（＝本当の出典は別の頁だと分かる）
どこにも見当たらない数字は、発言者が計算した数字（例：708,000×5%＝35,400）とみなして咎めない。
百分率（%）は決算書の数字から計算して言うことが多いので、決算書の頁を引いている場合は咎めない。

資料の「頁」は、決算書類なら読み取った科目の出典頁、ヒアリングメモなどの文書なら【p.N】の区切りで決める。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from schema import Financials, SourceRef

UNIT_TO_THOUSAND = {"千円": 1.0, "百万円": 1_000.0, "万円": 10.0, "億円": 100_000.0, "円": 0.001}
_AMOUNT = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(千円|百万円|万円|億円|円)?")
_WARI = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*割")
_PCT = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[%％]")
_PAGE_MARK = re.compile(r"【p\.?\s*(\d+)】")


@dataclass(frozen=True)
class Figure:
    raw: str          # 発言に書かれたとおりの字面
    kind: str         # amount / wari / pct
    value: float      # amount は千円、wari・pct は割合（0.6 など）
    tol: float        # 同じとみなす幅


@dataclass
class Page:
    doc: str
    page: str
    financial: bool
    amounts: list[float] = field(default_factory=list)
    ratios: list[tuple[str, float]] = field(default_factory=list)   # (kind, value)

    def label(self) -> str:
        return f"{self.doc} p.{self.page}"

    def has(self, f: Figure) -> bool:
        if f.kind == "amount":
            return any(abs(a - f.value) <= f.tol for a in self.amounts)
        return any(k == f.kind and abs(v - f.value) <= f.tol for k, v in self.ratios)


def _decimals(num: str) -> int:
    return len(num.split(".")[1]) if "." in num else 0


def extract(text: str) -> list[Figure]:
    """発言の中の金額と割合。単位のない数字は、3桁区切りのもの（千円とみなす）だけを拾う。"""
    out: list[Figure] = []
    for m in _AMOUNT.finditer(text):
        num, unit = m.group(1), m.group(2)
        tail = text[m.end():m.end() + 1]
        if unit is None and ("," not in num or tail in ("%", "％", "割", "か", "ヶ", "年", "月", "名", "人", "件")):
            continue
        scale = UNIT_TO_THOUSAND[unit or "千円"]
        value = float(num.replace(",", "")) * scale
        step = scale * 10 ** -_decimals(num)
        if value < 100:                    # 10万円未満の金額は照合に向かない（端数や件数と紛れる）
            continue
        out.append(Figure(m.group(0).strip(), "amount", value, max(1.0, step / 2)))
    for m in _WARI.finditer(text):
        v = float(m.group(1))
        out.append(Figure(m.group(0), "wari", v / 10, 10 ** -_decimals(m.group(1)) / 20))
    for m in _PCT.finditer(text):
        v = float(m.group(1))
        out.append(Figure(m.group(0), "pct", v / 100, 10 ** -_decimals(m.group(1)) / 200))
    return out


def _pages_of(ref: str | None) -> set[str]:
    return set(re.findall(r"\d+", ref or ""))


def build_index(fin: Financials | None, materials: dict[str, str]) -> dict[tuple[str, str], Page]:
    """引用できる資料を頁ごとに分け、その頁にある数字を集める。"""
    idx: dict[tuple[str, str], Page] = {}

    def page(doc: str, p: str, financial: bool) -> Page:
        return idx.setdefault((doc, p), Page(doc, p, financial))

    if fin is not None:
        for it in fin.items.values():
            if it.source.file and it.source.page:
                pg = page(it.source.file, str(it.source.page), True)
                pg.amounts += [float(v) for v in (it.cur, it.prev) if v is not None]
            for c in it.breakdown:
                if c.page and it.source.file:
                    pg = page(it.source.file, str(c.page), True)
                    pg.amounts += [float(v) for v in (c.cur, c.prev) if v is not None]
    for doc, text in materials.items():
        marks = list(_PAGE_MARK.finditer(text))
        chunks = [("1", text)] if not marks else [
            (m.group(1), text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)])
            for i, m in enumerate(marks)]
        for p, chunk in chunks:
            pg = page(doc, p, False)
            for f in extract(chunk):
                if f.kind == "amount":
                    pg.amounts.append(f.value)
                else:
                    pg.ratios.append((f.kind, f.value))
    return idx


def _mixups(text: str, cited: list[Page], index: dict[tuple[str, str], Page], seen: set[str]) -> list[str]:
    problems: list[str] = []
    for f in extract(text):
        if f.raw in seen or any(pg.has(f) for pg in cited):
            continue
        if f.kind == "pct" and any(pg.financial for pg in cited):
            continue                         # 決算書の数字から計算した百分率とみなす
        elsewhere = [pg for pg in index.values() if pg not in cited and pg.has(f)]
        if not elsewhere:
            continue                         # どこにもない数字は、計算した数字とみなす
        seen.add(f.raw)
        where = "、".join(pg.label() for pg in elsewhere[:2]) + ("ほか" if len(elsewhere) > 2 else "")
        problems.append(f"出典の取り違え：「{f.raw}」は引用された{'・'.join(pg.label() for pg in cited)}にはなく、"
                        f"{where}にあります。出典を直してください")
    return problems


def _inline(text: str, docs: list[str]) -> list[tuple[list[tuple[str, str]], str]]:
    """本文中の括弧書きの引用を拾い、([(資料名, 頁), …], その引用がかかる語句) を返す。

    括弧の中に「資料名 p.N」が一つでもあれば引用とみなし、中の引用はすべて拾う（「（A p.2、B p.3）」）。
    かかる語句＝直前の引用の終わり（または文の始まり）から、この括弧の終わりまで。
    「同 p.N」は直前に引用した資料を指す。
    """
    if not docs:
        return []
    names = "|".join(re.escape(d) for d in sorted(docs, key=len, reverse=True))
    ref = re.compile(r"(" + names + r"|同)\s*p\.?\s*(\d+)")
    out, last_doc, start = [], None, 0
    for g_start, g_end in _groups(text):
        group = text[g_start:g_end]
        refs = []
        for r in ref.finditer(group):
            doc = last_doc if r.group(1) == "同" else r.group(1)
            if doc is not None:
                refs.append((doc, r.group(2)))
                last_doc = doc
        if not refs:
            continue
        sent = max(text.rfind("。", 0, g_start) + 1, start)
        out.append((refs, text[sent:g_end]))
        start = g_end
    return out


def _groups(text: str) -> list[tuple[int, int]]:
    """いちばん外側の括弧の範囲（開き括弧から閉じ括弧まで）。資料名の中の「（架空）」のような入れ子も扱う。"""
    out, depth, begin = [], 0, 0
    for i, ch in enumerate(text):
        if ch in "（(":
            if depth == 0:
                begin = i
            depth += 1
        elif ch in "）)" and depth:
            depth -= 1
            if depth == 0:
                out.append((begin, i + 1))
    return out


def check(text: str, sources: list[SourceRef], index: dict[tuple[str, str], Page]) -> list[str]:
    """取り違えの疑いがある数字ごとに、差し戻しの理由を返す（なければ空）。

    二段で見る。(1) 本文中の「（資料名 p.N）」ごとに、その引用がかかる語句の数字がその頁にあるか。
    (2) 発言全体の数字が、出典欄に挙げたどれかの頁にあるか。
    """
    if not index:
        return []
    problems: list[str] = []
    seen: set[str] = set()
    for refs, span in _inline(text, sorted({d for d, _ in index})):
        pgs = [pg for key in refs if (pg := index.get(key))]
        if pgs:
            problems += _mixups(span, pgs, index, seen)
    cited = [pg for s in sources for p in _pages_of(s.page) if (pg := index.get((s.file or "", p)))]
    if cited:
        problems += _mixups(text, cited, index, seen)
    return problems
