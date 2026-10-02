"""知多精機株式会社（架空）のデモ用資料を作る：2期分の決算書（Excel）、ヒアリングメモ（Markdown）、動画シナリオ（Word）。

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
from docx.oxml.ns import nsdecls

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

# 2. Markdown (Chita_Seiki_Qualitative_Interview_Memo.md)　本文は利用者が確定した第4版
md_text = """# 知多精機株式会社 経営診断ヒアリングおよび定性調査メモ

- **調査実施日**：2026年9月
- **調査担当**：経営改善支援担当者（認定経営革新等支援機関）
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

# 3. Word (Chita_Seiki_Dynamism_Scenario.docx)
doc = Document()
for s in doc.sections:
    s.top_margin = Inches(1.0)
    s.bottom_margin = Inches(1.0)
    s.left_margin = Inches(1.0)
    s.right_margin = Inches(1.0)

COLOR_NAVY = RGBColor(31, 73, 125)
COLOR_GRAY = RGBColor(89, 89, 89)
COLOR_RED = RGBColor(192, 0, 0)
COLOR_GREEN = RGBColor(0, 128, 0)

p_title = doc.add_paragraph()
p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p_title.add_run("DiaDoc 審査員向けデモ動画シナリオ")
r.font.name, r.font.size, r.font.bold, r.font.color.rgb = "Yu Gothic", Pt(20), True, COLOR_NAVY

p_sub = doc.add_paragraph()
p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
p_sub.paragraph_format.space_after = Pt(20)
r = p_sub.add_run("定性×定量が織りなす「診断のダイナミズム」演出設計書（知多精機株式会社〔愛知県知多郡南知多町豊浜〕編）")
r.font.name, r.font.size, r.font.color.rgb = "Yu Gothic", Pt(11), COLOR_GRAY

# Callout
tbl_call = doc.add_table(rows=1, cols=1)
tbl_call.alignment = WD_TABLE_ALIGNMENT.CENTER
c_call = tbl_call.cell(0, 0)
c_call.width = Inches(6.5)
c_call._tc.get_or_add_tcPr().append(parse_xml(r'<w:shd {} w:fill="F2F5F8"/>'.format(nsdecls('w'))))
c_call._tc.get_or_add_tcPr().append(parse_xml(r'''<w:tcBorders {}><w:top w:val="none"/><w:left w:val="single" w:sz="24" w:space="0" w:color="1F497D"/><w:bottom w:val="none"/><w:right w:val="none"/></w:tcBorders>'''.format(nsdecls('w'))))
p_c = c_call.paragraphs[0]
r1 = p_c.add_run("【本資料の設計思想と真正性（知財クリアランス）】\n")
r1.font.name, r1.font.size, r1.font.bold, r1.font.color.rgb = "Yu Gothic", Pt(10), True, COLOR_NAVY
r2 = p_c.add_run("本ケースは、認定経営革新等支援機関の実務知見に基づき、製造業現場で頻出する構造的課題（B/S借入区分欠落・段取り替え非効率・現場職人の反発）を抽象化して完全新規に合成した「オリジナル架空ケース（Synthetic Data）」です。第三者著作権および守秘義務リスクを完全に排除しています。")
r2.font.name, r2.font.size = "Yu Gothic", Pt(9.5)
doc.add_paragraph().paragraph_format.space_after = Pt(10)

def add_sec(h_text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(h_text)
    r.font.name, r.font.size, r.font.bold, r.font.color.rgb = "Yu Gothic", Pt(13), True, COLOR_NAVY

add_sec("1. 企画意図：なぜ「定性データ」を入れるとダイナミズムが生まれるのか？")
p_b = doc.add_paragraph()
p_b.paragraph_format.line_spacing = 1.15
r = p_b.add_run("財務諸表の数値だけを動かしていると、DiaDocの高度な数理検算は伝わっても、審査員には「出来のよいExcel電卓」に見えてしまうリスクがあります。\n"
              "しかし、ここに「社長の焦り」「ベテラン工場長の反発」「銀行支店長の冷たい一言」といった定性データが投入されることで、システムは単なる計算機から『生きた意思決定法廷』へと昇華します。\n"
              "・Prof. Growth（成長派）は、若手エンジニアの改善提案を引用して果敢に攻める。\n"
              "・Dr. Rebuild（外科手術派）は、工場長の職人気質と精度狂いリスクを突いて冷徹にブレーキをかける。\n"
              "・Moderator Judge（審判）は、感情論を排し、客観的証拠に基づき減額採択（▽）を言い渡す。\n"
              "この対立と調停のプロセスこそが、審査員を惹きつけるDiaDoc最大の魅力です。")
r.font.name, r.font.size = "Yu Gothic", Pt(10)

add_sec("2. 審査員向けデモ動画（3分間）構成タイムライン")
tbl_t = doc.add_table(rows=1, cols=4)
tbl_t.alignment = WD_TABLE_ALIGNMENT.CENTER
headers_t = ["時間", "フェーズ", "画面アクション（実機操作）", "ナレーション・演出の急所"]
for i, h in enumerate(headers_t):
    tbl_t.rows[0].cells[i].text = h
    tbl_t.rows[0].cells[i]._tc.get_or_add_tcPr().append(parse_xml(r'<w:shd {} w:fill="1F497D"/>'.format(nsdecls('w'))))
    p = tbl_t.rows[0].cells[i].paragraphs[0]
    p.runs[0].font.name, p.runs[0].font.size, p.runs[0].font.bold = "Yu Gothic", Pt(9.5), True
    p.runs[0].font.color.rgb = RGBColor(255, 255, 255)

timeline_data = [
    ("0:00 - 0:30\n(30秒)", "導入\n課題提起", "一般的なチャットAIに赤字相談をして楽観的なハルシネーションが出ている画面スライド。", "「生成AIは経営者を心地よくさせるイエスマンになりがちです。しかし現場の決算書には欠落があり、資金ショート直前の企業でAIのハルシネーションは致命傷になります」"),
    ("0:30 - 1:00\n(30秒)", "基本構造\nAI統治", "DiaDocの全体画面。数理統治DDFゲートと対立エージェント（Growth vs Rebuild）の構造図。", "「DiaDocはAIの迎合を冷徹に防衛するAI統治機構です。計算は1円もLLMに任せずDDFが数理統治し、現場派と外科手術派が対立仮説を戦わせます」"),
    ("1:00 - 1:30\n(30秒)", "定量投入\n判定保留", "知多精機のExcelを投入。DDFが『長期借入金はあるが1年内返済区分なし』と赤字警告を出す。", "「中小企業の決算書には手抜きや欠落が多発します。DiaDocは鵜呑みにせず、資金判定を即座に『保留』とし、証拠の開示を逆請求します」"),
    ("1:30 - 1:55\n(25秒)", "支援担当者介入\n確定", "突合画面で支援担当者が返済予定表に基づき年10,000千円を入力。簡易営業CF 8,000千円に対し年間2,000千円の資金不足確定。", "「支援担当者が返済予定表を確認し数値を確定。この瞬間、年200万円の真の資金ショートが確定し、緊急トリアージが始まります」"),
    ("1:55 - 2:30\n(35秒)", "定性投入\n激論・減額", "定性調査メモを投入。Growthの年2,400千円削減案に対し、Rebuildが工場長メモを引用して反論。審判が1,000千円へ減額採択！", "「現場メモを投入するとAIが激論。Growthの改善策に、Rebuildが『工場長が反発している』と牙を剥く。審判は客観的リスクを認め減額採択します！」"),
    ("2:30 - 3:00\n(30秒)", "一括調達\n決着と統治", "遊休資材置場売却（8,000千円）で薄緑バナーへ転換。NotebookLM思想のレポート出力と第3のルート解説。", "「不足分は遊休地売却で補填し、完全合意。監査調書レポートが一撃で出力されます。機密データを中間SaaSに預けない第3のルートで守秘義務を死守します」")
]

for row_data in timeline_data:
    row_cells = tbl_t.add_row().cells
    for col_idx, text in enumerate(row_data):
        row_cells[col_idx].text = text
        p = row_cells[col_idx].paragraphs[0]
        p.runs[0].font.name, p.runs[0].font.size = "Yu Gothic", Pt(9)
        row_cells[col_idx]._tc.get_or_add_tcPr().append(parse_xml(r'''<w:tcBorders {}><w:top w:val="single" w:sz="4" w:space="0" w:color="D9D9D9"/><w:left w:val="single" w:sz="4" w:space="0" w:color="D9D9D9"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="D9D9D9"/><w:right w:val="single" w:sz="4" w:space="0" w:color="D9D9D9"/></w:tcBorders>'''.format(nsdecls('w'))))

doc.save("Chita_Seiki_Dynamism_Scenario.docx")
print("Saved Chita_Seiki_Dynamism_Scenario.docx")
