# Cloud Run へのデプロイ手順（公開デモ）

DiaDoc（Dialectic-BizDoctor）を Google Cloud Run に公開するための手順です。コマンドは Windows の PowerShell で書いています。前提は Google Cloud SDK（`gcloud`）が入っていることです。

## いつもの公開（2回目以降）

最初の準備（手順1）が済んでいれば、改修を公開するのは次の1行です。プロジェクトのフォルダで実行します。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy.ps1
```

`scripts\deploy.ps1` が、手順2〜5をまとめて行います。途中で問題が見つかれば、その場で理由を表示して止まり、公開中の版はそのまま残ります。

1. コミットしていないコードの変更がないか確かめる（data フォルダの「画面で試した跡」は無視する）
2. GitHub に送っていないコミットがあれば、送るかを聞く
3. 同梱するファイルの名前が英数字だけか確かめる
4. コミット済みの内容だけを `..\diadoc-deploy` に取り出す
5. 取り出した内容でテストを走らせる（公開するものそのものを試験する）
6. `gcloud run deploy` を実行する
7. 取り出したフォルダを片付け、URL と公開したコミットを表示する

オプション：`-SkipTests`（テストを省く）、`-Yes`（確認の問いにすべて「はい」と答える）。

`-ExecutionPolicy Bypass` は、この1回だけスクリプトの実行を許すための指定です。パソコンの設定は変えません。

## 0. 公開版の考え方（ステートレス）

- **見本だけを載せる。** イメージに入るのは、Git にコミットされた C001（アルファ製菓＝上場の加工食品メーカーを基にしたモデル企業）と C002（架空の窮境企業）の初期状態だけです。
- **ブラウザごとに専用の作業場所を作る。** 開いた人ごとに見本を一時フォルダへ複製して使います（`DBD_SESSION_SANDBOX=1`、Dockerfile で既定オン）。審査員が同時に開いても、論争・投入資料・実質化の調整・SQLite の途中状態は混ざりません。
- **消えてよい。** 作業場所は、6時間使われないか、コンテナが止まると消えます。次に開いた人は、いつも見本の状態から始まります。見本そのもの（`/app/data`）は読み取り専用で、書き換えられません。
- **キーはイメージに入れない。** Gemini の API キーは Secret Manager に置き、実行時に環境変数 `GEMINI_API_KEY` として渡します。`.env` は `.dockerignore` と `.gcloudignore` の両方で除外しています。

## 1. 最初に一度だけ行う準備

```powershell
# ログインとプロジェクトの選択
gcloud auth login
gcloud config set project <PROJECT_ID>

# 必要な API を有効にする
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

# Gemini API キーを Secret Manager に登録する
# PowerShell の echo は末尾に改行を付けるので、改行なしのファイルを経由して登録し、すぐ消す
Set-Content -Path key.txt -Value "<GEMINI_API_KEY>" -NoNewline -Encoding ascii
gcloud secrets create gemini-api-key --data-file=key.txt
Remove-Item key.txt

# Cloud Run の実行サービスアカウントに、シークレットの読み取りを許可する
$PN = gcloud projects describe <PROJECT_ID> --format="value(projectNumber)"
gcloud secrets add-iam-policy-binding gemini-api-key `
  --member="serviceAccount:$PN-compute@developer.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
```

キーを差し替えるときは、`gcloud secrets versions add gemini-api-key --data-file=key.txt` で新しい版を足します（`:latest` を参照しているので、次のデプロイから新しいキーが使われます）。

## 2. コミット済みの状態だけを取り出す

手元のフォルダには、画面で試したときの回次・途中状態・`.env` が残っていることがあります。公開版に混ぜないため、**コミット済みの内容だけを別フォルダに取り出して**、そこからデプロイします。

```powershell
cd C:\Users\MyProjectsOnWin\Dialectic-BizDoctor
git status                       # コミット漏れがないか確かめる（未コミットの変更は公開されない）
git worktree add ..\diadoc-deploy HEAD
cd ..\diadoc-deploy
```

`..\diadoc-deploy` には、最新のコミットと同じファイルだけが入ります（`.env` も実行時のファイルもありません）。

## 3. デプロイ

`..\diadoc-deploy` で実行します。

```powershell
gcloud run deploy diadoc `
  --source . `
  --region asia-northeast1 `
  --execution-environment gen2 `
  --allow-unauthenticated `
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest `
  --set-env-vars GEMINI_MODEL=gemini-3.8-flash `
  --max-instances 1 `
  --concurrency 20 `
  --session-affinity `
  --memory 2Gi `
  --timeout 3600
```

初回は、ビルドしたイメージを置く Artifact Registry のリポジトリ（`cloud-run-source-deploy`）を作るか聞かれるので `Y` と答えます。完了すると `https://diadoc-xxxxx.asia-northeast1.run.app` のような URL が表示されます。

| 指定 | 理由 |
|---|---|
| `--source .` | Dockerfile を使って Cloud Build でイメージを作る |
| `--set-secrets` | API キーを Secret Manager から環境変数として渡す（イメージにもソースにも残らない） |
| `--execution-environment gen2` | 第2世代の実行環境（ふつうの Linux に近く、ファイルの扱いに制約が少ない） |
| `--max-instances 1` | Streamlit は画面の状態をコンテナのメモリに持つ。台数が分かれると、再接続のときに別のコンテナにつながって状態を失うことがあるため、デモでは1台に固定する |
| `--concurrency 20` | 1台で同時に受け持つ接続の上限。審査員が数人同時に開く程度を想定 |
| `--session-affinity` | 同じ利用者を同じコンテナにつなぐ |
| `--memory 2Gi` | Cloud Run のファイルはメモリ上にある。見本の複製（1人あたり約0.3MB）と画面の状態に余裕を持たせる |
| `--timeout 3600` | Streamlit は WebSocket で接続を保つ。上限（60分）まで切れないようにする。切れても画面は自動で再接続する |

**発言を台本で動かすデモにしたい場合**（Gemini の利用料をかけない、応答を速くする）は、`--set-env-vars GEMINI_MODEL=gemini-3.8-flash,DBD_DEBATE=mock` とします。資料の読み取りだけを台本にするときは `DBD_EXTRACTOR=mock` を足します。

**「Container import failed」で止まった場合**：ビルドは通ったのに、Cloud Run がイメージを読み込めない状態です。2026-09-28 の初回公開では、**同梱データの日本語のファイル名**が原因でした（ヒアリングメモと C001 の検算表。いまは英数字のファイル名にして、画面や出典に出す日本語の名前は `inputs/titles.json` に持たせています）。Dockerfile はビルド中にファイル名を確かめ、英数字以外があればその場で止まります。見本に資料を足すときは、ファイル名を英数字にして、表示名を `titles.json` に書いてください。あわせて、依存関係はハードリンクを使わずにコピーで入れています（念のための対処）。

**権限エラーでビルドが止まった場合**は、Cloud Build が使うサービスアカウントに権限を付けてから、もう一度デプロイします。

```powershell
gcloud projects add-iam-policy-binding <PROJECT_ID> `
  --member="serviceAccount:$PN-compute@developer.gserviceaccount.com" `
  --role="roles/cloudbuild.builds.builder"
```

## 4. 公開後の確認

1. 表示された URL を開き、サイドバーに「公開デモ：このブラウザ専用の作業場所で動いています」と出ることを確かめる。
2. C002 を選び、「▶ 1手進める」で論争が動くこと、「意思決定ツリー」タブでツリーが描かれることを確かめる。
3. 別のブラウザ（またはシークレットウィンドウ）で同じ URL を開き、1 で進めた論争がそちらには出ない（見本の状態から始まる）ことを確かめる。
4. ログは `gcloud run services logs read diadoc --region asia-northeast1 --limit 50` で見られる。

## 5. 後片付け

```powershell
# 取り出したフォルダを消す（元のフォルダに戻ってから）
cd C:\Users\MyProjectsOnWin\Dialectic-BizDoctor
git worktree remove ..\diadoc-deploy
```

## 6. 知っておくべき制約

- **公開 URL になる。** `--allow-unauthenticated` を付けると誰でも開けます。投入された資料は Gemini API に送られ、利用料が発生します。審査期間が終わったら、`gcloud run services update diadoc --region asia-northeast1 --no-allow-unauthenticated` で非公開にするか、`gcloud run services delete diadoc --region asia-northeast1` で削除してください。
- **アップロードは30MBまで。** Cloud Run のリクエスト上限（32MiB）に合わせて Dockerfile で制限しています。
- **作業は保存されない。** 作業場所は一時的です。実運用にするなら、Cloud Storage や Firestore への保存に切り替える必要があります。
- **意思決定ツリーはブラウザで描く。** `st.graphviz_chart` はレイアウトをブラウザ側で行うため、コンテナに OS の graphviz（`dot`）は入れていません。

## 7. 手元で Docker を使って確かめる（任意）

Docker が入っていれば、Cloud Run と同じ形で手元で動かせます。

```powershell
docker build -t diadoc .
docker run --rm -p 8080:8080 -e DBD_DEBATE=mock -e DBD_EXTRACTOR=mock diadoc
```

ブラウザで `http://localhost:8080` を開きます。本物の Gemini で試すときは `-e GEMINI_API_KEY=<キー>` を付け、`DBD_DEBATE` と `DBD_EXTRACTOR` を外します（キーはコマンド履歴に残るので、試したあとは履歴を消してください）。
