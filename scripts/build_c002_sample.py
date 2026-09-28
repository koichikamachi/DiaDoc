"""架空の窮境企業モデル（C002）の財務データを作る。

実在の会社ではない。地方の老舗金属プレス部品メーカーを想定した架空の数字で、検算38項目がすべて一致するように
内訳から合計を積み上げて作る。画面では「架空モデル」と明示する（CLAUDE.md 決定事項 2026-09-27）。

使い方（プロジェクトのルートで）:  python scripts/build_c002_sample.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tools.standard_accounts import LABELS, META  # noqa: E402

OUT = ROOT / "data/companies/C002_sample_crisis/runs/run_001_initial/inputs/financials.json"
KESSAN, UCHIWAKE, GAIYO = "決算報告書第62期（架空）", "勘定科目内訳明細書第62期（架空）", "金融機関向け決算概要第62期（架空）"

# 内訳（前期, 当期）千円。合計行はここに書かず、下で積み上げる
LEAF: dict[str, tuple[int, int]] = {
    # 流動資産
    "cash": (96_000, 51_000), "nr": (22_000, 18_000), "ar": (221_000, 196_000), "rm": (44_000, 41_000),
    "pp": (3_400, 3_200), "oca": (5_800, 6_800), "ada1": (-1_100, -1_000),
    # 有形・無形・投資その他
    "bld": (136_000, 128_000), "str": (10_300, 9_500), "mac": (172_000, 146_000), "veh": (7_900, 6_200),
    "tool": (5_200, 4_300), "land": (152_000, 152_000), "lease": (18_500, 13_800), "cip": (0, 0),
    "sw": (2_900, 2_100), "oint": (600, 600),
    "inv": (8_100, 8_400), "aff": (0, 0), "cap": (1_000, 1_000), "ltl": (0, 0), "ltpp": (1_500, 1_200),
    "dep": (3_600, 3_600), "oinv": (43_090, 13_800), "ada2": (0, 0),
    # 流動負債
    "ap": (141_000, 128_000), "stl": (150_000, 180_000), "cltd": (92_000, 96_000), "cbond": (0, 0),
    "cls": (4_600, 4_800), "oap": (23_000, 21_000), "acc": (15_000, 14_000), "refund": (0, 0), "tax": (290, 290),
    "ctax": (8_100, 6_500), "wh": (3_300, 3_200), "dr": (0, 0), "bonus": (9_000, 0), "ocl": (2_600, 2_400),
    # 固定負債
    "bond": (0, 0), "ltd": (408_000, 312_000), "ltdep": (0, 0), "lls": (14_400, 9_600), "ret": (41_000, 38_000),
    "sbp": (0, 0), "dtl": (0, 0), "oltl": (20_000, 30_000),
    # 純資産（繰越利益剰余金は下で動きから求める）
    "cs": (30_000, 30_000), "csr": (0, 0), "lr": (7_500, 7_500), "gr": (20_000, 20_000), "ts": (0, 0), "oci": (0, 0),
    # 損益
    "sales": (1_320_000, 1_180_000), "sell": (62_000, 58_000), "adm": (101_000, 96_000),
    "ii": (30, 20), "div": (150, 150), "ooi": (4_820, 3_830),
    "ie": (15_600, 16_800), "bde": (0, 0), "idle": (0, 0), "ooe": (1_400, 1_200),
    "sg1": (2_000, 0), "sg2": (0, 0), "sl1": (800, 1_500), "sl2": (0, 0), "sl3": (0, 0), "sl4": (0, 0), "sl5": (0, 0),
    "ctx": (290, 290), "dtx": (0, 0),
    # 製造原価と売上原価
    "mat": (575_000, 520_000), "lab": (312_000, 300_000), "exp": (246_000, 240_000),
    "e_dep": (45_000, 42_000), "e_pow": (36_000, 38_000), "e_rep": (15_000, 16_000), "e_fuel": (9_500, 9_000),
    "e_sup": (11_500, 11_000),
    "bwip": (38_000, 36_000), "ewip": (36_000, 33_000),
    "bfg": (61_000, 58_000), "pur": (14_000, 12_000), "trf": (0, 0), "efg": (58_000, 52_000), "emd": (0, 0),
    # 株主資本等変動
    "dvd": (0, 0), "grt": (0, 0),
    # 勘定科目内訳（監視科目）
    "officer_loan": (20_000, 30_000), "suspense": (900, 2_300), "ins_reserve": (43_090, 13_800),
}
SGA = {  # 販管費内訳（前期, 当期）。雑費は販管費合計に合わせて最後に求める
    "sga_officer": (18_000, 18_000), "sga_salary": (55_000, 52_000), "sga_bonus": (4_000, 0),
    "sga_welfare_legal": (11_600, 11_000), "sga_welfare": (1_900, 1_500), "sga_freight": (34_000, 31_000),
    "sga_dep": (6_500, 6_000), "sga_rent": (4_800, 4_800), "sga_lease": (3_600, 3_600),
    "sga_insurance": (3_900, 2_400), "sga_tax": (3_200, 3_100), "sga_fee": (5_300, 5_500), "sga_util": (2_900, 2_800),
    "sga_travel": (2_700, 2_200), "sga_comm": (1_400, 1_300), "sga_entertain": (1_500, 900), "sga_adv": (900, 600),
}
RE_BEFORE_PREV = 64_090  # 前々期末の繰越利益剰余金（前期の動きから逆算しない。前期首として置く）

PAGES = {"BS": (KESSAN, "2"), "PL": (KESSAN, "3"), "製造原価": (KESSAN, "4"), "売上原価調整": (KESSAN, "3"),
         "株主資本等変動": (KESSAN, "5"), "販管費内訳": (KESSAN, "6"), "主要経営指標": (GAIYO, "1")}
UCHIWAKE_PAGES = {"officer_loan": "3", "suspense": "1", "ins_reserve": "2"}
ABSENT = {k for k, v in LEAF.items() if v == (0, 0) and k not in ("dvd", "grt", "tax")}


def build() -> dict:
    v = {k: list(p) for k, p in LEAF.items()}
    v.update({k: list(p) for k, p in SGA.items()})

    def s(*keys, i):
        return sum((-v[k[1:]][i] if k.startswith("-") else v[k][i]) for k in keys)

    for i in (0, 1):
        # 原価の流れ
        v.setdefault("tmc", [0, 0])[i] = s("mat", "lab", "exp", i=i)
        v.setdefault("cgm", [0, 0])[i] = s("tmc", "bwip", "-ewip", i=i)
        v.setdefault("cogs", [0, 0])[i] = s("bfg", "cgm", "pur", "-trf", "-efg", "-emd", i=i)
        v.setdefault("fg", [0, 0])[i] = s("efg", "emd", i=i)
        v.setdefault("wip", [0, 0])[i] = v["ewip"][i]
        # 損益
        v.setdefault("gp", [0, 0])[i] = s("sales", "-cogs", i=i)
        v.setdefault("sga", [0, 0])[i] = s("sell", "adm", i=i)
        v.setdefault("sga_misc", [0, 0])[i] = v["sga"][i] - sum(p[i] for p in SGA.values())
        v.setdefault("op", [0, 0])[i] = s("gp", "-sga", i=i)
        v.setdefault("tnoi", [0, 0])[i] = s("ii", "div", "ooi", i=i)
        v.setdefault("tnoe", [0, 0])[i] = s("ie", "bde", "idle", "ooe", i=i)
        v.setdefault("ord", [0, 0])[i] = s("op", "tnoi", "-tnoe", i=i)
        v.setdefault("tsg", [0, 0])[i] = s("sg1", "sg2", i=i)
        v.setdefault("tsl", [0, 0])[i] = s("sl1", "sl2", "sl3", "sl4", "sl5", i=i)
        v.setdefault("pbt", [0, 0])[i] = s("ord", "tsg", "-tsl", i=i)
        v.setdefault("ttx", [0, 0])[i] = s("ctx", "dtx", i=i)
        v.setdefault("ni", [0, 0])[i] = s("pbt", "-ttx", i=i)
    # 繰越利益剰余金：期首＋純利益−配当−積立
    re_prev = RE_BEFORE_PREV + v["ni"][0] - v["dvd"][0] - v["grt"][0]
    v["re"] = [re_prev, re_prev + v["ni"][1] - v["dvd"][1] - v["grt"][1]]
    for i in (0, 1):
        v.setdefault("tca", [0, 0])[i] = s("cash", "nr", "ar", "fg", "wip", "rm", "pp", "oca", "ada1", i=i)
        v.setdefault("tppe", [0, 0])[i] = s("bld", "str", "mac", "veh", "tool", "land", "lease", "cip", i=i)
        v.setdefault("tint", [0, 0])[i] = s("sw", "oint", i=i)
        v.setdefault("tinv", [0, 0])[i] = s("inv", "aff", "cap", "ltl", "ltpp", "dep", "oinv", "ada2", i=i)
        v.setdefault("tfa", [0, 0])[i] = s("tppe", "tint", "tinv", i=i)
        v.setdefault("ta", [0, 0])[i] = s("tca", "tfa", i=i)
        v.setdefault("tcl", [0, 0])[i] = s("ap", "stl", "cltd", "cbond", "cls", "oap", "acc", "refund", "tax", "ctax",
                                           "wh", "dr", "bonus", "ocl", i=i)
        v.setdefault("tltl", [0, 0])[i] = s("bond", "ltd", "ltdep", "lls", "ret", "sbp", "dtl", "oltl", i=i)
        v.setdefault("tl", [0, 0])[i] = s("tcl", "tltl", i=i)
        v.setdefault("tre", [0, 0])[i] = s("lr", "gr", "re", i=i)
        v.setdefault("tsh", [0, 0])[i] = s("cs", "csr", "tre", "ts", i=i)
        v.setdefault("tna", [0, 0])[i] = s("tsh", "oci", i=i)
        v.setdefault("tle", [0, 0])[i] = s("tl", "tna", i=i)
        for k, src in (("k_sales", "sales"), ("k_ni", "ni"), ("k_na", "tna"), ("k_ta", "ta")):
            v.setdefault(k, [0, 0])[i] = v[src][i]
    # 資金繰りを数字で説明できるように、資産と負債・純資産の一致を確かめておく
    assert v["ta"] == v["tle"], (v["ta"], v["tle"])

    items = {}
    for key, (prev, cur) in v.items():
        statement, section = META[key]
        if statement == "勘定科目内訳":
            file, page = UCHIWAKE, UCHIWAKE_PAGES[key]
        else:
            file, page = PAGES[statement]
        absent = key in ABSENT
        items[key] = {
            "statement": statement, "section": section, "label": LABELS[key],
            "source_label": "（記載なし）" if absent else LABELS[key], "prev": prev, "cur": cur,
            "mapping": "該当なし（0）" if absent else "対応", "is_total": False,
            "source": {"file": file, "page": page},
            "note": "架空モデルの決算書にこの行はない。検算のため0として置く" if absent else "",
        }
    return {
        "company_id": "C002", "fiscal_period": "第62期（架空。2025年4月1日〜2026年3月31日）", "basis": "単体",
        "unit": "千円", "rounding": "truncate_thousand",
        "rounding_note": "架空モデル。内訳から合計を積み上げて作ったため、端数差は生じない",
        "documents": {
            KESSAN: {"title": "架空モデル 第62期 決算報告書（貸借対照表・損益計算書・製造原価報告書・株主資本等変動計算書・販管費内訳）"},
            UCHIWAKE: {"title": "架空モデル 第62期 勘定科目内訳明細書"},
            GAIYO: {"title": "架空モデル 第62期 金融機関向け決算概要"},
        },
        "items": items, "supplementary": {},
    }


if __name__ == "__main__":
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"書き出しました：{OUT.relative_to(ROOT)}（{len(data['items'])}科目）")
