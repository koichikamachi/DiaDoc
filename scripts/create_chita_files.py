"""知多精機株式会社（架空）のデモ用資料を作る：2期分の決算書（Excel）、ヒアリングメモ（Markdown）、借入金返済予定表（Markdown）、動画シナリオ（Word）。

会社・金融機関はすべて架空（知多精機株式会社＝愛知県知多郡南知多町豊浜、メインバンク＝豊浜信用金庫）。
人間の介入・確定の主体は「支援担当者」と呼ぶ（個人名・特定の士業名は書かない）。
出力先は work/demo/chita_seiki/（git・公開イメージの対象外）。
"""
import os
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.oxml import OxmlElement

# 出力先：work/demo/chita_seiki/（git・イメージの対象外）
OUT = Path(__file__).resolve().parents[1] / "work" / "demo" / "chita_seiki"
OUT.mkdir(parents=True, exist_ok=True)
os.chdir(OUT)

# 1. Excel (Chita_Seiki_Financials_2Periods.xlsx)
wb = openpyxl.Workbook()
font_title = Font(name="Yu Gothic", size=14, bold=True, color="1F497D")
font_header = Font(name="Yu Gothic", size=11, bold=True, color="FFFFFF")
font_bold = Font(name="Yu Gothic", size=10, bold=True)
font_regular = Font(name="Yu Gothic", size=10)
font_italic = Font(name="Yu Gothic", size=9, italic=True, color="595959")
fill_header = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
fill_subtotal = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")
fill_total = PatternFill(start_color="B8CCE4", end_color="B8CCE4", fill_type="solid")
thin_side = Side(border_style="thin", color="D9D9D9")
thick_side = Side(border_style="medium", color="1F497D")
double_side = Side(border_style="double", color="1F497D")
border_subtotal = Border(top=thin_side, bottom=thick_side)
border_total = Border(top=thin_side, bottom=double_side)
align_left = Alignment(horizontal="left", vertical="center")
align_right = Alignment(horizontal="right", vertical="center")
align_center = Alignment(horizontal="center", vertical="center")

headers = ["科目", "前期（第23期）", "当期（第24期）", "増減額", "備考"]

# B/S
ws_bs = wb.active
ws_bs.title = "貸借対照表"
ws_bs.views.sheetView[0].showGridLines = True
ws_bs.cell(row=1, column=1, value="貸 借 対 照 表").font = font_title
ws_bs.cell(row=2, column=1, value="会社名：知多精機株式会社（単位：千円）").font = font_italic
for col_idx, h in enumerate(headers, 1):
    c = ws_bs.cell(row=4, column=col_idx, value=h)
    c.font, c.fill, c.alignment = font_header, fill_header, align_center

bs_rows = [
    (0, "【資産の部】", None, None, ""),
    (0, "Ⅰ 流動資産", None, None, ""),
    (1, "  現金及び預金", 18200, 13900, ""),
    (1, "  受取手形", 14500, 15200, ""),
    (1, "  売掛金", 28400, 30500, ""),
    (1, "  製品", 6200, 6200, ""),
    (1, "  仕掛品", 4500, 4600, ""),
    (1, "  原材料", 5500, 6000, ""),
    (1, "  その他流動資産", 1200, 1400, ""),
    (2, "流動資産合計", 78500, 77800, ""),
    (0, "Ⅱ 固定資産", None, None, ""),
    (0, "  1. 有形固定資産", None, None, ""),
    (1, "    建物", 27000, 25800, ""),
    (1, "    機械装置", 32000, 28000, "NC旋盤・5軸MC"),
    (1, "    土地", 35000, 35000, "本社敷地および旧資材置場"),
    (2, "  有形固定資産合計", 94000, 88800, ""),
    (0, "  2. 投資その他の資産", None, None, ""),
    (1, "    投資有価証券", 2000, 2000, "取引先持株"),
    (1, "    敷金保証金", 1500, 1500, ""),
    (2, "  投資その他の資産合計", 3500, 3500, ""),
    (2, "固定資産合計", 97500, 92300, ""),
    (3, "資産合計", 176000, 170100, ""),
    (0, "【負債の部】", None, None, ""),
    (0, "Ⅰ 流動負債", None, None, ""),
    (1, "  支払手形", 11200, 10800, ""),
    (1, "  買掛金", 18500, 19400, ""),
    (1, "  短期借入金", 10000, 10000, "手形貸付"),
    (1, "  未払費用", 3800, 4100, ""),
    (1, "  未払法人税等", 500, 800, ""),
    (1, "  その他流動負債", 1500, 1700, ""),
    (2, "流動負債合計", 45500, 46800, ""),
    (0, "Ⅱ 固定負債", None, None, ""),
    (1, "  長期借入金", 100000, 90000, "豊浜信用金庫ほか"),
    (1, "  退職給付引当金", 8500, 8500, ""),
    (2, "固定負債合計", 108500, 98500, ""),
    (3, "負債合計", 154000, 145300, ""),
    (0, "【純資産の部】", None, None, ""),
    (0, "Ⅰ 株主資本", None, None, ""),
    (1, "  資本金", 10000, 10000, ""),
    (0, "  利益剰余金", None, None, ""),
    (1, "    利益準備金", 1000, 1000, ""),
    (1, "    繰越利益剰余金", 11000, 13800, ""),
    (2, "  利益剰余金合計", 12000, 14800, ""),
    (2, "株主資本合計", 22000, 24800, ""),
    (3, "純資産合計", 22000, 24800, ""),
    (3, "負債及び純資産合計", 176000, 170100, "")
]

r = 5
for level, name, p23, p24, note in bs_rows:
    ws_bs.cell(row=r, column=1, value=name).font = font_bold if level in (0,2,3) else font_regular
    if p23 is not None and p24 is not None:
        for c_idx, val in [(2, p23), (3, p24)]:
            cell = ws_bs.cell(row=r, column=c_idx, value=val)
            cell.number_format = "#,##0"
            cell.alignment = align_right
        cell_diff = ws_bs.cell(row=r, column=4, value=f"=C{r}-B{r}")
        cell_diff.number_format = "#,##0"
        cell_diff.alignment = align_right
    c_note = ws_bs.cell(row=r, column=5, value=note)
    c_note.font, c_note.alignment = font_italic, align_left
    if level == 2:
        for col in range(1, 6):
            ws_bs.cell(row=r, column=col).fill = fill_subtotal
            ws_bs.cell(row=r, column=col).font = font_bold
            ws_bs.cell(row=r, column=col).border = border_subtotal
    elif level == 3:
        for col in range(1, 6):
            ws_bs.cell(row=r, column=col).fill = fill_total
            ws_bs.cell(row=r, column=col).font = font_bold
            ws_bs.cell(row=r, column=col).border = border_total
    r += 1

# P/L
ws_pl = wb.create_sheet(title="損益計算書")
ws_pl.views.sheetView[0].showGridLines = True
ws_pl.cell(row=1, column=1, value="損 益 計 算 書").font = font_title
ws_pl.cell(row=2, column=1, value="会社名：知多精機株式会社（単位：千円）").font = font_italic
for col_idx, h in enumerate(headers, 1):
    c = ws_pl.cell(row=4, column=col_idx, value=h)
    c.font, c.fill, c.alignment = font_header, fill_header, align_center

pl_rows = [
    (1, "Ⅰ 売上高", 230000, 242000, "NC切削加工・試作部品"),
    (1, "Ⅱ 売上原価", 179400, 188760, ""),
    (2, "売上総利益", 50600, 53240, "粗利率 22.0%"),
    (0, "Ⅲ 販売費及び一般管理費", None, None, ""),
    (1, "  役員報酬", 12000, 12000, "代表者1名"),
    (1, "  給料手当", 16500, 17200, "事務・営業部門"),
    (1, "  旅費交通費", 1200, 1300, ""),
    (1, "  通信運搬費", 2100, 2250, ""),
    (1, "  減価償却費（販管）", 800, 800, "社屋・備品"),
    (1, "  賃借料", 3600, 3600, "営業車両・駐車場"),
    (1, "  その他経費", 10200, 10490, ""),
    (2, "販売費及び一般管理費合計", 46400, 47640, ""),
    (3, "営業利益", 4200, 5600, ""),
    (0, "Ⅳ 営業外収益", None, None, ""),
    (1, "  受取利息配当金", 20, 30, ""),
    (1, "  雑収入", 380, 420, "切削屑売却益等"),
    (2, "営業外収益合計", 400, 450, ""),
    (0, "Ⅴ 営業外費用", None, None, ""),
    (1, "  支払利息", 2400, 2250, "借入金利息（平均2.2%）"),
    (2, "営業外費用合計", 2400, 2250, ""),
    (3, "経常利益", 2200, 3800, ""),
    (3, "税引前当期純利益", 2200, 3800, "特別損益なし"),
    (1, "法人税、住民税及び事業税", 700, 1000, ""),
    (3, "当期純利益", 1500, 2800, "")
]

r = 5
for level, name, p23, p24, note in pl_rows:
    ws_pl.cell(row=r, column=1, value=name).font = font_bold if level in (0,2,3) else font_regular
    if p23 is not None and p24 is not None:
        for c_idx, val in [(2, p23), (3, p24)]:
            cell = ws_pl.cell(row=r, column=c_idx, value=val)
            cell.number_format = "#,##0"
            cell.alignment = align_right
        cell_diff = ws_pl.cell(row=r, column=4, value=f"=C{r}-B{r}")
        cell_diff.number_format = "#,##0"
        cell_diff.alignment = align_right
    c_note = ws_pl.cell(row=r, column=5, value=note)
    c_note.font, c_note.alignment = font_italic, align_left
    if level == 2:
        for col in range(1, 6):
            ws_pl.cell(row=r, column=col).fill = fill_subtotal
            ws_pl.cell(row=r, column=col).font = font_bold
            ws_pl.cell(row=r, column=col).border = border_subtotal
    elif level == 3:
        for col in range(1, 6):
            ws_pl.cell(row=r, column=col).fill = fill_total
            ws_pl.cell(row=r, column=col).font = font_bold
            ws_pl.cell(row=r, column=col).border = border_total
    r += 1

# C/R
ws_cr = wb.create_sheet(title="製造原価報告書")
ws_cr.views.sheetView[0].showGridLines = True
ws_cr.cell(row=1, column=1, value="製 造 原 価 報 告 書").font = font_title
ws_cr.cell(row=2, column=1, value="会社名：知多精機株式会社（単位：千円）").font = font_italic
for col_idx, h in enumerate(headers, 1):
    c = ws_cr.cell(row=4, column=col_idx, value=h)
    c.font, c.fill, c.alignment = font_header, fill_header, align_center

cr_rows = [
    (0, "Ⅰ 材料費", None, None, ""),
    (1, "  期首材料棚卸高", 5000, 5500, ""),
    (1, "  当期材料仕入高", 65500, 68260, "特殊鋼・ステンレス・チタン"),
    (1, "  期末材料棚卸高", 5500, 6000, "控除項目"),
    (2, "材料費合計", 65000, 67760, ""),
    (0, "Ⅱ 労務費", None, None, ""),
    (1, "  賃金手当（製造現場）", 62000, 65000, "残業代 約3,600千円を含む"),
    (1, "  法定福利費", 9300, 9750, ""),
    (1, "  賞与引当金繰入", 3100, 3250, ""),
    (2, "労務費合計", 74400, 78000, ""),
    (0, "Ⅲ 経費", None, None, ""),
    (1, "  外注加工費", 22000, 23500, "熱処理・表面処理"),
    (1, "  減価償却費（製造）", 4400, 4400, "NC旋盤・5軸MC"),
    (1, "  電力料", 6800, 7200, "動力電力"),
    (1, "  消耗品費", 3200, 3500, "切削工具・刃具"),
    (1, "  修繕費", 1600, 1900, "機械メンテナンス"),
    (1, "  その他経費", 2400, 2600, ""),
    (2, "経費合計", 40400, 43100, ""),
    (3, "当期総製造費用", 179800, 188860, "材料費+労務費+経費"),
    (1, "期首仕掛品棚卸高", 4100, 4500, ""),
    (1, "期末仕掛品棚卸高", 4500, 4600, "控除項目"),
    (3, "当期製品製造原価", 179400, 188760, "")
]

r = 5
for level, name, p23, p24, note in cr_rows:
    ws_cr.cell(row=r, column=1, value=name).font = font_bold if level in (0,2,3) else font_regular
    if p23 is not None and p24 is not None:
        for c_idx, val in [(2, p23), (3, p24)]:
            cell = ws_cr.cell(row=r, column=c_idx, value=val)
            cell.number_format = "#,##0"
            cell.alignment = align_right
        cell_diff = ws_cr.cell(row=r, column=4, value=f"=C{r}-B{r}")
        cell_diff.number_format = "#,##0"
        cell_diff.alignment = align_right
    c_note = ws_cr.cell(row=r, column=5, value=note)
    c_note.font, c_note.alignment = font_italic, align_left
    if level == 2:
        for col in range(1, 6):
            ws_cr.cell(row=r, column=col).fill = fill_subtotal
            ws_cr.cell(row=r, column=col).font = font_bold
            ws_cr.cell(row=r, column=col).border = border_subtotal
    elif level == 3:
        for col in range(1, 6):
            ws_cr.cell(row=r, column=col).fill = fill_total
            ws_cr.cell(row=r, column=col).font = font_bold
            ws_cr.cell(row=r, column=col).border = border_total
    r += 1

for ws in [ws_bs, ws_pl, ws_cr]:
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 16
    ws.column_dimensions["E"].width = 44

wb.save("Chita_Seiki_Financials_2Periods.xlsx")
print("Saved Chita_Seiki_Financials_2Periods.xlsx")

# 2. Markdown (Chita_Seiki_Qualitative_Interview_Memo.md)　本文は利用者が確定した第4版（冒頭に架空の断り書きを足した）
md_text = """# 知多精機株式会社 経営診断ヒアリングおよび定性調査メモ

> ※ このメモは、デモ用に作った架空のケースです。会社・金融機関・人物は、すべて実在しません。

- **調査実施日**：2026年9月
- **調査担当**：経営改善の支援担当者
- **対象企業**：知多精機株式会社（愛知県知多郡南知多町豊浜）
- **業種**：精密金属加工・NC切削加工業（資本金10,000千円、従業員18名）
- **対象期**：第24期決算完了直後（年商242,000千円）

---

## 1. 診断ミッション・背景
- 直近決算（第24期）は営業利益5,600千円（2.3%）、経常利益3,800千円と黒字を確保。
- メインバンク（豊浜信用金庫）からの長期借入金残高が90,000千円あり、**年間10,000千円（月約83.3万円）の元金均等返済**が発生。
- 減価償却費（5,200千円）を加味した簡易営業キャッシュフローは8,000千円にとどまり、**年間約2,000千円（年200万円）の資金ショート（資金流出）**が構造化。
- 現預金は13,900千円（月商20,167千円の約0.69ヶ月分）まで減少しており、賞与月や納税期に資金ショートの危機がある。

---

## 2. 経営者（代表取締役社長・48歳、2代目承継3年目）ヒアリング
- **技術力への自負と現場の課題**：
  「難削材（チタン・SUS316等）の精密加工技術には高い評価をいただいているが、近年は小ロット・多品種の短納期発注が増加している。その結果、製造現場での段取り替えが1日に何度も発生し、作業効率が著しく低下している。」
- **資金繰りへの焦り**：
  「先代の設備投資（5年前に導入した大型5軸マシニングセンタ2基）の借入金返済が重く、毎月の元金返済が口座から引き落とされるのが苦しい。このままでは冬の賞与資金の手当てがつかない。」

---

## 3. 工場長（62歳、ベテラン職人頭）および現場ヒアリング（重要・定量データ）
- **労務費と残業の実態**：
  - 製造現場の賃金手当65,000千円のうち、**恒常的な残業代が年間約3,600千円（月平均30万円）**を占めている。
  - 主因は「NC旋盤・マシニングセンタの治具段取り替え」にあり、1回あたり平均45分を要している。
- **改善ポテンシャル（Prof. Growthの論拠）**：
  - 若手エンジニアより「治具の共通プレート化と段取り標準化」の提案あり。
  - 段取り替え時間を45分から20分（▲25分短縮）に圧縮できれば、夜間残業を大幅に削減可能。
  - **試算効果：年間約2,400千円（月20万円）の労務費削減が可能**。
- **組織的障壁・現場の反発（Dr. Rebuildの反論根拠）**：
  - 一方で、工場長およびベテラン職人2名は**「治具を共通化すると微妙なビビリ（振動）が出て、チタン加工の精度（公差±0.005mm）が狂うリスクがある」**として治具標準化に強く反対している。
  - 職人の説得と新治具のテスト加工・精度検証には最低でも4〜6ヶ月を要し、**初年度から満額2,400千円の効果を出すのは不可能。初年度はせいぜい年1,000千円程度（立ち上がり4割）に留まる見込み**。

---

## 4. 取引先・営業環境分析（4P・市場動向）
- **主要顧客A社（工作機械大手、売上シェア45%）**：
  - 安定した発注はあるものの、毎期2%のコストダウン要請（単価切り下げ）を受けており、粗利率は18%まで低下。
- **成長顧客B社（医療機器・内視鏡部品メーカー、売上シェア20%）**：
  - 要求精度は厳しいが、**粗利率が35%と極めて高い**。
  - B社より「月間200万円程度の追加発注（チタン製シャフト加工）を打診」されているが、現在の現場の段取り逼迫を理由に断っている状態。
  - 段取り効率化で現場キャパシティが空けば、B社向け売上増により**年間約1,500千円の追加限界利益**を獲得できる余地がある。

---

## 5. 資産状況・換金可能資産（一括調達レバー）
- **本社裏手の「旧第2資材置場」（土地約120坪）**：
  - 10年前に資材置き場として購入（帳簿価格：土地の一部として計上）。
  - 現在はプレハブの物置が1棟あるのみで、ほぼ遊休地状態となっている。
  - 近隣の工業地域地価公示・不動産業者への事前ヒアリングによると、**更地売却により約8,000千円〜10,000千円での売却・換金が可能（買い手候補の物流会社あり）**。
  - 担保設定は外れており、売却資金は全額手元流動性に充当可能。

---

## 6. メインバンク（豊浜信用金庫）のスタンス
- 担当融資役席との面談メモ：
  「借入金利息は正常に払われているが、年間10,000千円の約定返済原資（営業CF）が不足している点を融資部も懸念している。決算書上に1年内返済の区分記載がない点も指摘された。抜本的な経営改善計画書が提示されない限り、追加の短期運転資金枠設定やリスケ（返済猶予）の相談には応じられない。」
"""
with open("Chita_Seiki_Qualitative_Interview_Memo.md", "w", encoding="utf-8") as f:
    f.write(md_text)
print("Saved Chita_Seiki_Qualitative_Interview_Memo.md")

# 3. 借入金返済予定表（Chita_Seiki_Loan_Repayment_Schedule.md）
# 動画で「返済予定表を確かめて、年間の約定返済額を確定する」場面に使う、決算書の外にある証拠（架空）。
# これはアプリに投入しない。支援担当者が目で確かめ、突合マトリクスの「支援担当者による確定」に金額と根拠を入れる。
schedule_text = """# 借入金返済予定表（知多精機株式会社・第25期分）

> ※ デモ用に作った架空の書類です。会社・金融機関は、すべて実在しません。

- **借入先**：豊浜信用金庫
- **借入の種類**：証書貸付（設備資金。5軸マシニングセンタ2基）
- **第24期末の残高**：90,000千円
- **返済の方法**：元金均等返済（毎月末）
- **毎月の元金返済**：約833千円
- **第25期の約定返済額（元金）**：年10,000千円
- **第25期末の残高（予定）**：80,000千円

| 期 | 期首残高 | 元金返済（年） | 期末残高 |
|---|---:|---:|---:|
| 第24期（実績） | 100,000 | 10,000 | 90,000 |
| 第25期（予定） | 90,000 | 10,000 | 80,000 |
| 第26期（予定） | 80,000 | 10,000 | 70,000 |

（単位：千円。利息は別途）
"""
with open("Chita_Seiki_Loan_Repayment_Schedule.md", "w", encoding="utf-8") as f:
    f.write(schedule_text)
print("Saved Chita_Seiki_Loan_Repayment_Schedule.md")

# 4. Word (Chita_Seiki_Dynamism_Scenario.docx)
# 筋は一本：「資料が増えるたびに、診断が動く」。アプリの実際の動きに合わせて書く
# （不足が出ただけではトリアージに入らない。計算と採否の判定はプログラム、読み取りと議論は Gemini）。
doc = Document()
for sec in doc.sections:
    sec.top_margin = sec.bottom_margin = sec.left_margin = sec.right_margin = Inches(1.0)

COLOR_NAVY = RGBColor(31, 73, 125)
COLOR_GRAY = RGBColor(89, 89, 89)
FONT = "Meiryo"   # 利用者の既定の Word 書式：全文メイリオ、見出し13pt、本文10.5pt、表内9pt、ヘッダーに標題、フッターに頁番号


def run(par, text, size=10, bold=False, color=None):
    r = par.add_run(text)
    r.font.name, r.font.size, r.font.bold = FONT, Pt(size), bold
    r._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)   # 日本語の字形にも同じフォントを当てる
    if color is not None:
        r.font.color.rgb = color
    return r


def heading(text):
    par = doc.add_paragraph()
    par.paragraph_format.space_before, par.paragraph_format.space_after = Pt(14), Pt(4)
    run(par, text, 13, True, COLOR_NAVY)


def body(text):
    par = doc.add_paragraph()
    par.paragraph_format.space_before = Pt(0.5)
    run(par, text, 10.5)


def bullets(items):
    for it in items:
        par = doc.add_paragraph(style="List Bullet")
        run(par, it, 10.5)


def table(headers, rows, widths=None):
    tbl = doc.add_table(rows=1, cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.style = "Table Grid"
    tbl.autofit = False
    for i, h in enumerate(headers):
        cell = tbl.rows[0].cells[i]
        cell.text = ""
        cell._tc.get_or_add_tcPr().append(parse_xml(r'<w:shd {} w:fill="1F497D"/>'.format(nsdecls('w'))))
        run(cell.paragraphs[0], h, 9, True, RGBColor(255, 255, 255))
    for row in rows:
        cells = tbl.add_row().cells
        for i, text in enumerate(row):
            cells[i].text = ""
            run(cells[i].paragraphs[0], text, 9)
    if widths:
        for i, w in enumerate(widths):
            tbl.columns[i].width = Inches(w)
        for row in tbl.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)


par = doc.add_paragraph()
par.alignment = WD_ALIGN_PARAGRAPH.CENTER
run(par, "DiaDoc デモ動画シナリオ（3分）", 20, True, COLOR_NAVY)
par = doc.add_paragraph()
par.alignment = WD_ALIGN_PARAGRAPH.CENTER
par.paragraph_format.space_after = Pt(16)
run(par, "知多精機株式会社〔愛知県知多郡南知多町豊浜〕編（架空のケース）", 11, False, COLOR_GRAY)

heading("要約")
body("この動画は、一つの会社の診断を最初から最後まで追う。筋は一本で、「資料が増えるたびに、診断が動く」。"
     "決算書だけでは資金の判定を保留し、返済予定表で不足が確定し、現場のメモで議論の中身が変わり、反論で提案が減額され、報告書になる。"
     "伝えることは一つ：計算と、発言を採用するかどうかの判定はプログラムが行い、AIは資料を読み、議論する。判断に必要な資料がなければ、答えずに止まる。")

heading("1. このケースについて")
body("知多精機株式会社は、デモ用に作った架空の会社である。メインバンクの豊浜信用金庫も架空である。"
     "製造業の現場でよくある悩み（借入金の返済区分が決算書にない、段取り替えの非効率、現場の反発）を組み合わせて、数字も文章も新しく作った。"
     "実在の会社・教材の数字や文章は使っていない。")
table(["数字", "額（千円）", "出どころ"], [
    ("売上高（第24期）", "242,000", "損益計算書"),
    ("簡易営業CF", "8,000", "経常利益 3,800 − 法人税等 1,000 ＋ 減価償却費 5,200（製造 4,400＋販管 800）"),
    ("年間の約定返済額", "10,000", "借入金返済予定表（決算書には1年内返済の区分がない）"),
    ("返済後の資金収支", "△2,000", "8,000 − 10,000。毎年 2,000千円（200万円）の不足"),
    ("段取り標準化による労務費の削減", "2,400 → 初年度 1,000", "ヒアリングメモ 3（若手の提案と、工場長の反対）"),
    ("B社向け追加受注の限界利益", "1,500", "ヒアリングメモ 4"),
    ("旧第2資材置場の売却", "8,000〜10,000（一回限り）", "ヒアリングメモ 5"),
], widths=[2.1, 1.5, 2.9])

heading("2. 3分の構成")
table(["時間", "場面", "画面の操作", "ナレーション"], [
    ("0:00〜0:20", "何をするアプリか",
     "決算書（Excel）を資料ドックに入れる。検算が通り「適格」と出る。",
     "「DiaDocは、中小企業の決算書から、会社のお金が足りるかを診断するアプリです。まず決算書を入れます。足し算が合っているかは、AIではなくプログラムが検算します」"),
    ("0:20〜0:50", "判定保留",
     "右の欄の残余月数が「判定保留」。宿題に「【必須】借入金返済予定表」が出る。",
     "「借入金が9,000万円あるのに、決算書には毎年の返済額が書かれていません。DiaDocは返済ゼロとして『資金は十分』とは答えません。判定を保留し、返済予定表を請求します」"),
    ("0:50〜1:15", "支援担当者による確定",
     "返済予定表を確かめ、「支援担当者による確定」に年10,000千円と根拠を入れる。不足 年2,000千円が出る。",
     "「支援担当者が返済予定表を確かめ、年1,000万円と確定します。根拠のない入力は受け付けません。この瞬間、毎年200万円の不足が数字で確定します」"),
    ("1:15〜1:45", "現場のメモで議論が変わる",
     "ヒアリングメモを追加して「次のラウンドへ」。Growth が段取り標準化（年2,400千円）を、メモを根拠に提案する。",
     "「ここで現場のヒアリングメモを入れます。提案に足場ができます。段取り替えを45分から20分に縮めれば、残業代が年240万円減る、という提案です」"),
    ("1:45〜2:15", "反論と減額採択",
     "Rebuild が工場長の反対（精度への懸念、検証に4〜6か月）を引いて反論。プログラムが提案を 1,000千円に減額して数える。発言の下の「根拠と審査」を開く。",
     "「反対する役のAIが、同じメモから工場長の反対を引きます。初年度に見込めるのは100万円。反論が審査を通ると、プログラムは提案を満額では数えません」"),
    ("2:15〜2:45", "結論と報告書",
     "結論のカード。「レポートを保存」「診断経緯の文章化」。要約と、金融機関提出用の文章を映す。",
     "「議論が閉じると、結論と、そこに至った経緯が報告書になります。数字はすべて記録と照合しています」"),
    ("2:45〜3:00", "全体を引きで",
     "画面全体。終わりのカード（公開URL）。",
     "「計算と判定はプログラム。AIは読み、議論する。最後に決めるのは人です。DiaDocでした」"),
], widths=[0.8, 1.1, 2.3, 2.3])

heading("3. 撮影の前に決めること")
bullets([
    "本番の Gemini は、押すたびに発言が変わる。ナレーションは、撮れた議論に合わせて最後に確定する。上の表の金額（2,400→1,000 など）は、メモに書いてある数字で、発言がそのとおりになるとは限らない",
    "議論がどう閉じるかも回によって違う（改善策で不足を埋めて決着／埋まらずに道の選択へ／上限で要追加検討）。何度か通して、筋がいちばん伝わる回を使う",
    "一手の待ち時間（7〜20秒）は編集で詰める。画面の動き（数字が変わる、差し戻しの印、結論のカード）は切らない",
    "遊休地の売却（一回限りの資金）が出た回なら、「毎年続く改善」と「一度きりのお金」を分けて数えることを一言添える",
])

heading("4. 言わないこと")
bullets([
    "「不足が出たのでトリアージが始まる」：不足が出ただけでは、道の選択（トリアージ）には入らない。改善策を尽くしても届かないときだけ",
    "「計算は1円もAIに任せない」：決算書の読み取りは Gemini が行う。言うなら「検算と判定はプログラムが行う」",
    "アプリにない仕組みの話（外部サービスの名前、守秘の方式など）",
    "会社を患者に、AIを医師に置き換えるたとえ話",
])

heading("5. 投入する資料と順番")
table(["順番", "ファイル", "入れ方"], [
    ("1", "Chita_Seiki_Financials_2Periods.xlsx", "資料ドック → 財務書類として投入（新しい会社の第1次分析に入る）"),
    ("2", "Chita_Seiki_Loan_Repayment_Schedule.md", "投入しない。画面の外で確かめ、「支援担当者による確定」に年10,000千円と根拠を入れる"),
    ("3", "Chita_Seiki_Qualitative_Interview_Memo.md", "資料ドック → 定性資料として追加（青いボタンを押すまでが投入）"),
], widths=[0.6, 2.9, 3.0])

hp = doc.sections[0].header.paragraphs[0]
run(hp, "DiaDoc デモ動画シナリオ（3分）　知多精機株式会社編（架空のケース）", 9)
fp = doc.sections[0].footer.paragraphs[0]
fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
fr = run(fp, "", 10)
for tag, text in (("begin", None), (None, "PAGE"), ("end", None)):
    el = OxmlElement("w:fldChar") if tag else OxmlElement("w:instrText")
    if tag:
        el.set(qn("w:fldCharType"), tag)
    else:
        el.text = text
    fr._r.append(el)

doc.save("Chita_Seiki_Dynamism_Scenario.docx")
print("Saved Chita_Seiki_Dynamism_Scenario.docx")
