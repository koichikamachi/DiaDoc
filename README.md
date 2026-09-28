# DiaDoc（ディアドック） | Dialectic-BizDoctor

**対立仮説検証による自律型経営診断システム**

財務諸表と定性情報（マーケティング4P）を起点に、立場の異なる複数のエージェント（再生派・成長派・調査派・調停役）が論争し、根拠のない主張を機械的に退けながら、経営診断と改善計画を絞り込む。決着しない争点は「このデータがあれば決まる」というデータ請求（宿題リスト）として出力する。

- 根拠がなければ止まる：主張には出典（書類と頁）と決着条件が必要。欠ければ審判が機械判定で退け・差し戻す
- 読み取った数値は論争の前に検算する：許容差＝内訳件数n（最低2単位）。不一致なら論争に進まない
- 過去の分析は凍結し、書き換えない：分析回次ごとに当時の論争・検算・判断を再現できる

内部名（フォルダ・パッケージ名）は `dialectic-bizdoctor`。設計の詳細は [CLAUDE.md](CLAUDE.md)、Cloud Run への配置は [deploy.md](deploy.md) を参照。

## 起動

```powershell
pip install streamlit pandas plotly graphviz pydantic google-genai openpyxl python-dotenv pytest
pytest
streamlit run src/ui/app.py
```

`.env.example` を `.env` にコピーして `GEMINI_API_KEY` を入れると、投入資料の読み取りが Gemini になる。キーがなければモック（制作サンプルを返し、ファイルは読まない）で動く。

## 読み取りだけを試す

```powershell
python src/tools/ingest_cli.py <資料のパス> --compare
```

`data/` には何も書かない。`--compare` を付けると、手作業で検算済みの制作サンプルと1科目ずつ突き合わせる。

## 構成

| 場所 | 役割 |
|---|---|
| `src/core/guardrails.py` | 検算ゲートと形式審査（LLMを使わない決定論的部分） |
| `src/core/runs.py` | 企業と分析回次の保管庫（凍結・引き継ぎ・上書き禁止） |
| `src/tools/file_ingest.py` | 投入資料の読み取り（Gemini 構造化出力 → 標準科目 → 検算） |
| `src/tools/standard_accounts.py` | 標準科目と別名辞書 |
| `src/ui/app.py` | Streamlit の画面 |
| `data/companies/` | 企業ごとの分析回次（制作サンプル：C001） |

制作サンプルの数値はアルファ製菓 第73期 有価証券報告書（単体）の公開情報に基づく。外部に示す際は匿名化する。
