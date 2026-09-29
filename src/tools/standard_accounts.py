"""標準科目の一覧と別名辞書（CLAUDE.md 6.6）。

key はシステム内部の識別子。label は標準科目名。synonyms は原資料で使われうる科目名（別名）。
同じ語が複数の標準科目に当てはまりうるもの（AMBIGUOUS）は、表の区分なしには自動で当てはめない。
"""

from __future__ import annotations

# (key, 表, 区分, 標準科目名, 合計行か)
ACCOUNTS: tuple[tuple[str, str, str, str, bool], ...] = (
    ('cash', 'BS', '流動資産', '現金預金', False),
    ('nr', 'BS', '流動資産', '受取手形', False),
    ('ar', 'BS', '流動資産', '売掛金', False),
    ('fg', 'BS', '流動資産', '製品・商品', False),
    ('wip', 'BS', '流動資産', '仕掛品', False),
    ('rm', 'BS', '流動資産', '原材料', False),
    ('stock', 'BS', '流動資産', '棚卸資産（一括表示）', False),
    ('pp', 'BS', '流動資産', '前払費用', False),
    ('oca', 'BS', '流動資産', 'その他流動資産', False),
    ('ada1', 'BS', '流動資産', '貸倒引当金（流動）', False),
    ('tca', 'BS', '流動資産', '流動資産合計', True),
    ('bld', 'BS', '有形固定資産', '建物', False),
    ('str', 'BS', '有形固定資産', '構築物', False),
    ('mac', 'BS', '有形固定資産', '機械装置', False),
    ('veh', 'BS', '有形固定資産', '車両運搬具', False),
    ('tool', 'BS', '有形固定資産', '工具器具備品', False),
    ('land', 'BS', '有形固定資産', '土地', False),
    ('lease', 'BS', '有形固定資産', 'リース資産', False),
    ('cip', 'BS', '有形固定資産', '建設仮勘定', False),
    ('tppe', 'BS', '有形固定資産', '有形固定資産合計', True),
    ('sw', 'BS', '無形固定資産', 'ソフトウェア', False),
    ('oint', 'BS', '無形固定資産', 'その他無形', False),
    ('tint', 'BS', '無形固定資産', '無形固定資産合計', True),
    ('inv', 'BS', '投資その他', '投資有価証券', False),
    ('aff', 'BS', '投資その他', '関係会社株式', False),
    ('cap', 'BS', '投資その他', '出資金', False),
    ('ltl', 'BS', '投資その他', '長期貸付金', False),
    ('ltpp', 'BS', '投資その他', '長期前払費用', False),
    ('dep', 'BS', '投資その他', '差入保証金', False),
    ('oinv', 'BS', '投資その他', 'その他投資', False),
    ('ada2', 'BS', '投資その他', '貸倒引当金（固定）', False),
    ('tinv', 'BS', '投資その他', '投資その他の資産合計', True),
    ('tfa', 'BS', '固定資産', '固定資産合計', True),
    ('ta', 'BS', '資産', '資産合計', True),
    ('np', 'BS', '流動負債', '支払手形', False),
    ('ap', 'BS', '流動負債', '買掛金', False),
    ('stl', 'BS', '流動負債', '短期借入金', False),
    ('cltd', 'BS', '流動負債', '1年内返済長期借入金', False),
    ('cbond', 'BS', '流動負債', '1年内償還社債', False),
    ('cls', 'BS', '流動負債', 'リース債務（流動）', False),
    ('oap', 'BS', '流動負債', '未払金', False),
    ('acc', 'BS', '流動負債', '未払費用', False),
    ('refund', 'BS', '流動負債', '返金負債', False),
    ('tax', 'BS', '流動負債', '未払法人税等', False),
    ('ctax', 'BS', '流動負債', '未払消費税', False),
    ('wh', 'BS', '流動負債', '預り金', False),
    ('dr', 'BS', '流動負債', '前受収益', False),
    ('bonus', 'BS', '流動負債', '賞与引当金', False),
    ('ocl', 'BS', '流動負債', 'その他流動負債', False),
    ('tcl', 'BS', '流動負債', '流動負債合計', True),
    ('bond', 'BS', '固定負債', '社債', False),
    ('ltd', 'BS', '固定負債', '長期借入金', False),
    ('ltdep', 'BS', '固定負債', '長期預り保証金', False),
    ('lls', 'BS', '固定負債', 'リース債務（固定）', False),
    ('ret', 'BS', '固定負債', '退職給付引当金', False),
    ('sbp', 'BS', '固定負債', '役員株式給付引当金', False),
    ('dtl', 'BS', '固定負債', '繰延税金負債', False),
    ('oltl', 'BS', '固定負債', 'その他固定負債', False),
    ('tltl', 'BS', '固定負債', '固定負債合計', True),
    ('tl', 'BS', '負債', '負債合計', True),
    ('cs', 'BS', '純資産', '資本金', False),
    ('csr', 'BS', '純資産', '資本準備金', False),
    ('lr', 'BS', '純資産', '利益準備金', False),
    ('gr', 'BS', '純資産', '別途積立金', False),
    ('re', 'BS', '純資産', '繰越利益剰余金', False),
    ('tre', 'BS', '純資産', '利益剰余金合計', True),
    ('ts', 'BS', '純資産', '自己株式', False),
    ('tsh', 'BS', '純資産', '株主資本合計', True),
    ('oci', 'BS', '純資産', '評価差額金', False),
    ('tna', 'BS', '純資産', '純資産合計', True),
    ('tle', 'BS', '負債純資産', '負債純資産合計', True),
    ('sales', 'PL', '売上', '売上高', False),
    ('cogs', 'PL', '売上原価', '売上原価', False),
    ('gp', 'PL', '利益', '売上総利益', True),
    ('sell', 'PL', '販管費', '販売費', False),
    ('adm', 'PL', '販管費', '一般管理費', False),
    ('sga', 'PL', '販管費', '販管費合計', True),
    ('op', 'PL', '利益', '営業利益', True),
    ('ii', 'PL', '営業外収益', '受取利息', False),
    ('div', 'PL', '営業外収益', '受取配当金', False),
    ('ooi', 'PL', '営業外収益', '雑収入', False),
    ('tnoi', 'PL', '営業外収益', '営業外収益合計', True),
    ('ie', 'PL', '営業外費用', '支払利息', False),
    ('bde', 'PL', '営業外費用', '貸倒引当金繰入額', False),
    ('idle', 'PL', '営業外費用', '休止固定資産減価償却費', False),
    ('ooe', 'PL', '営業外費用', '雑損失', False),
    ('tnoe', 'PL', '営業外費用', '営業外費用合計', True),
    ('ord', 'PL', '利益', '経常利益', True),
    ('sg1', 'PL', '特別利益', '固定資産売却益', False),
    ('sg2', 'PL', '特別利益', '投資有価証券売却益', False),
    ('tsg', 'PL', '特別利益', '特別利益合計', True),
    ('sl1', 'PL', '特別損失', '固定資産除却損', False),
    ('sl2', 'PL', '特別損失', '固定資産売却損', False),
    ('sl3', 'PL', '特別損失', '投資有価証券評価損', False),
    ('sl4', 'PL', '特別損失', 'リース解約損', False),
    ('sl5', 'PL', '特別損失', '解決金', False),
    ('tsl', 'PL', '特別損失', '特別損失合計', True),
    ('pbt', 'PL', '利益', '税引前当期純利益', True),
    ('ctx', 'PL', '税金', '法人税、住民税及び事業税', False),
    ('dtx', 'PL', '税金', '法人税等調整額', False),
    ('ttx', 'PL', '税金', '法人税等合計', True),
    ('ni', 'PL', '利益', '当期純利益', True),
    ('mat', '製造原価', '製造費用', '材料費', False),
    ('bmat', '製造原価', '材料費内訳', '期首材料棚卸高', False),
    ('mpur', '製造原価', '材料費内訳', '当期材料仕入高', False),
    ('emat', '製造原価', '材料費内訳', '期末材料棚卸高', False),
    ('lab', '製造原価', '製造費用', '労務費', False),
    ('exp', '製造原価', '製造費用', '経費', False),
    ('e_dep', '製造原価', '経費内訳', '減価償却費（製造）', False),
    ('e_fuel', '製造原価', '経費内訳', '燃料費', False),
    ('e_pow', '製造原価', '経費内訳', '電力費', False),
    ('e_sup', '製造原価', '経費内訳', '消耗器具備品費', False),
    ('e_rep', '製造原価', '経費内訳', '修繕費（製造）', False),
    ('tmc', '製造原価', '製造費用', '当期総製造費用', True),
    ('bwip', '製造原価', '仕掛品', '期首仕掛品', False),
    ('wip_chg', '製造原価', '仕掛品', '仕掛品増減（期首−期末）', False),
    ('ewip', '製造原価', '仕掛品', '期末仕掛品', False),
    ('cgm', '製造原価', '製品', '当期製品製造原価', True),
    ('bfg', '売上原価調整', '製品', '期首製品', False),
    ('pur', '売上原価調整', '商品', '当期商品仕入高', False),
    ('trf', '売上原価調整', '振替', '他勘定振替高', False),
    ('efg', '売上原価調整', '製品', '期末製品', False),
    ('emd', '売上原価調整', '商品', '期末商品', False),
    ('dvd', '株主資本等変動', '繰越利益剰余金', '剰余金の配当', False),
    ('grt', '株主資本等変動', '繰越利益剰余金', '別途積立金の積立', False),
    ('k_sales', '主要経営指標', '照合', '売上高（指標欄）', True),
    ('k_ni', '主要経営指標', '照合', '当期純利益（指標欄）', True),
    ('k_na', '主要経営指標', '照合', '純資産（指標欄）', True),
    ('k_ta', '主要経営指標', '照合', '総資産（指標欄）', True),
    ('sga_officer', '販管費内訳', '人件費', '役員報酬', False),
    ('sga_salary', '販管費内訳', '人件費', '給料手当', False),
    ('sga_bonus', '販管費内訳', '人件費', '賞与・賞与引当金繰入額', False),
    ('sga_retire', '販管費内訳', '人件費', '退職給付費用', False),
    ('sga_welfare_legal', '販管費内訳', '人件費', '法定福利費', False),
    ('sga_welfare', '販管費内訳', '人件費', '福利厚生費', False),
    ('sga_freight', '販管費内訳', '物流', '荷造運賃', False),
    ('sga_adv', '販管費内訳', '販売促進', '広告宣伝費', False),
    ('sga_promo', '販管費内訳', '販売促進', '販売促進費', False),
    ('sga_entertain', '販管費内訳', '販売', '交際費', False),
    ('sga_travel', '販管費内訳', '一般', '旅費交通費', False),
    ('sga_comm', '販管費内訳', '一般', '通信費', False),
    ('sga_util', '販管費内訳', '一般', '水道光熱費', False),
    ('sga_repair', '販管費内訳', '一般', '修繕費（販管費）', False),
    ('sga_rent', '販管費内訳', '一般', '地代家賃', False),
    ('sga_lease', '販管費内訳', '一般', '賃借料', False),
    ('sga_insurance', '販管費内訳', '一般', '保険料', False),
    ('sga_tax', '販管費内訳', '一般', '租税公課', False),
    ('sga_dep', '販管費内訳', '一般', '減価償却費（販管費）', False),
    ('sga_fee', '販管費内訳', '一般', '支払手数料', False),
    ('sga_rd', '販管費内訳', '一般', '研究開発費', False),
    ('sga_supplies', '販管費内訳', '一般', '消耗品費', False),
    ('sga_misc', '販管費内訳', '一般', '雑費', False),
    ('suspense', '勘定科目内訳', '監視科目', '仮払金', False),
    ('other_recv', '勘定科目内訳', '監視科目', '未収入金', False),
    ('st_loan', '勘定科目内訳', '監視科目', '短期貸付金', False),
    ('officer_loan', '勘定科目内訳', '監視科目', '役員借入金', False),
    ('ins_reserve', '勘定科目内訳', '監視科目', '保険積立金', False),
)

SYNONYMS: dict[str, tuple[str, ...]] = {
    'cash': ('現金及び預金', '現金・預金', '現預金', '現金預金'),
    'ar': ('売掛金',),
    'nr': ('受取手形',),
    'fg': ('商品及び製品', '製品・商品'),
    'wip': ('仕掛品',),
    'rm': ('原材料及び貯蔵品', '原材料'),
    'stock': ('棚卸資産', 'たな卸資産', '在庫'),
    'np': ('支払手形',),
    'mac': ('機械及び装置', '機械装置'),
    'tool': ('工具、器具及び備品', '工具器具備品', '器具備品'),
    'veh': ('車両運搬具',),
    'sw': ('ソフトウエア', 'ソフトウェア'),
    'inv': ('投資有価証券',),
    'ap': ('買掛金',),
    'oap': ('未払金',),
    'acc': ('未払費用',),
    'tax': ('未払法人税等',),
    'ctax': ('未払消費税等', '未払消費税'),
    'wh': ('預り金',),
    'bonus': ('賞与引当金',),
    'ret': ('退職給付引当金',),
    'ltd': ('長期借入金',),
    'stl': ('短期借入金',),
    'cs': ('資本金',),
    're': ('繰越利益剰余金',),
    'ts': ('自己株式',),
    'oci': ('その他有価証券評価差額金',),
    'sales': ('売上高', '売上'),
    'cogs': ('売上原価',),
    'gp': ('売上総利益',),
    'sga': ('販売費及び一般管理費', '販売費及び一般管理費合計', '販管費'),
    'op': ('営業利益',),
    'ord': ('経常利益',),
    'pbt': ('税引前当期純利益',),
    'ni': ('当期純利益',),
    'ii': ('受取利息',),
    'div': ('受取配当金',),
    'ie': ('支払利息',),
    'ooi': ('雑収入',),
    'ooe': ('雑損失',),
    'mat': ('材料費',),
    'bmat': ('期首材料棚卸高', '期首原材料棚卸高'),
    'mpur': ('当期材料仕入高', '材料仕入高', '原材料仕入高'),
    'emat': ('期末材料棚卸高', '期末原材料棚卸高'),
    'wip_chg': ('仕掛品増減', '仕掛品増減額'),
    'lab': ('労務費',),
    'tmc': ('当期総製造費用',),
    'cgm': ('当期製品製造原価',),
    'pur': ('当期商品仕入高', '商品仕入高'),
    'sga_officer': ('役員報酬',),
    'sga_salary': ('給料手当', '給料及び手当', '給与手当', '給料'),
    'sga_bonus': ('賞与',),
    'sga_retire': ('退職給付費用',),
    'sga_welfare_legal': ('法定福利費',),
    'sga_welfare': ('福利厚生費',),
    'sga_freight': ('荷造運賃', '発送費', '発送配達費', '運搬費', '荷造発送費', '運賃'),
    'sga_adv': ('広告宣伝費', '広告費', '宣伝費'),
    'sga_promo': ('販売促進費', '販促費'),
    'sga_entertain': ('交際費', '接待交際費'),
    'sga_travel': ('旅費交通費',),
    'sga_comm': ('通信費',),
    'sga_util': ('水道光熱費',),
    'sga_rent': ('地代家賃',),
    'sga_lease': ('賃借料', 'リース料'),
    'sga_insurance': ('保険料',),
    'sga_tax': ('租税公課',),
    'sga_fee': ('支払手数料',),
    'sga_rd': ('研究開発費', '試験研究費'),
    'sga_supplies': ('消耗品費', '事務用消耗品費', '工場消耗品・消耗品費'),
    'sga_misc': ('雑費',),
    'suspense': ('仮払金',),
    'other_recv': ('未収入金', '未収金'),
    'st_loan': ('短期貸付金',),
    'officer_loan': ('役員借入金',),
    'ins_reserve': ('保険積立金',),
}

AMBIGUOUS: frozenset[str] = frozenset(['減価償却費', '修繕費', 'その他', '賞与引当金繰入額', '貸倒引当金', 'リース債務', '社債', '合計'])

# 符号の約束：株主資本等変動計算書では△（マイナス）で表示されるが、標準科目では減少額を正の数で持つもの。
# 検算（繰越利益剰余金の動き）は「前期末＋純利益−配当−積立」で計算するため、正の数でなければならない。
POSITIVE_MAGNITUDE: frozenset[str] = frozenset({"dvd", "grt", "emat"})

# 会社によっては行そのものがない科目。行がなければ検算では0とみなし「未確認」にしない（検算の定義で optional を付ける）
OPTIONAL_KEYS: frozenset[str] = frozenset({"stl"})

KEYS: frozenset[str] = frozenset(a[0] for a in ACCOUNTS)
LABELS: dict[str, str] = {a[0]: a[3] for a in ACCOUNTS}
TOTAL_KEYS: frozenset[str] = frozenset(a[0] for a in ACCOUNTS if a[4])
META: dict[str, tuple[str, str]] = {a[0]: (a[1], a[2]) for a in ACCOUNTS}


def _normalize_label(s: str) -> str:
    return "".join((s or "").split()).replace("（", "(").replace("）", ")")


def _build_reverse() -> dict[str, str]:
    rev: dict[str, str] = {}
    clash: set[str] = set()
    for key, words in SYNONYMS.items():
        for w in words + (LABELS[key],):
            n = _normalize_label(w)
            if n in rev and rev[n] != key:
                clash.add(n)
            rev[n] = key
    for n in clash:
        rev.pop(n, None)
    return rev


_REVERSE = _build_reverse()


def _strip_brackets(n: str) -> list[str]:
    """「(期首材料棚卸高)」「給料手当(販管)」のような括弧を外した候補（外側 → 末尾の順）。"""
    import re

    out = []
    if n.startswith("(") and n.endswith(")") and n.count("(") == 1:
        out.append(n[1:-1])
    m = re.fullmatch(r"(.+?)\([^()]*\)", n)
    if m:
        out.append(m.group(1))
    return out


def key_for_label(label: str) -> str | None:
    """原資料の科目名から標準科目のキーを引く。曖昧な語や未登録の語は None。

    完全一致がなければ、括弧で囲んだ行（内訳の注記）と、末尾の括弧書き（「給料手当（販管）」など）を外して引き直す。
    """
    n = _normalize_label(label)
    ambiguous = {_normalize_label(a) for a in AMBIGUOUS}
    for cand in [n, *_strip_brackets(n)]:
        if not cand or cand in ambiguous:
            continue
        if cand in _REVERSE:
            return _REVERSE[cand]
    return None


def catalog_text() -> str:
    """プロンプトに渡す標準科目の一覧（key: 標準科目名［表・区分］ 別名）。"""
    out = []
    for key, st, sec, label, is_total in ACCOUNTS:
        syn = "、".join(w for w in SYNONYMS.get(key, ()) if w != label)
        sign = "　符号：△表示でも減少額を正の数で書く" if key in POSITIVE_MAGNITUDE else ""
        out.append(f"{key}: {label}［{st}・{sec}{'・合計' if is_total else ''}］" + (f"　別名：{syn}" if syn else "") + sign)
    return "\n".join(out)
