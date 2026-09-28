# Cloud Run へのデプロイ手順

Dialectic-BizDoctor を Google Cloud Run に載せるための簡易手順。前提は Google Cloud SDK（`gcloud`）が入っていること。

## 1. 最初に一度だけ行う準備

```powershell
# ログインとプロジェクトの選択
gcloud auth login
gcloud config set project <PROJECT_ID>

# 必要な API を有効にする
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

# Gemini API キーを Secret Manager に登録する（キーをイメージやソースに残さないため）
# PowerShell の echo は末尾に改行を付けるので、改行なしのファイルを経由して登録し、すぐ消す
Set-Content -Path key.txt -Value "<GEMINI_API_KEY>" -NoNewline -Encoding ascii
gcloud secrets create gemini-api-key --data-file=key.txt
Remove-Item key.txt

# Cloud Run の実行サービスアカウントに、シークレットの読み取りを許可する
gcloud secrets add-iam-policy-binding gemini-api-key `
  --member="serviceAccount:<PROJECT_NUMBER>-compute@developer.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
```

`<PROJECT_NUMBER>` は `gcloud projects describe <PROJECT_ID> --format="value(projectNumber)"` で分かる。

## 2. デプロイ（ワンライナー）

プロジェクトのフォルダ（Dockerfile のある場所）で実行する。

```powershell
gcloud run deploy dialectic-bizdoctor --source . --region asia-northeast1 --allow-unauthenticated --set-secrets GEMINI_API_KEY=gemini-api-key:latest --set-env-vars GEMINI_MODEL=gemini-3.8-flash --max-instances 1 --session-affinity --memory 1Gi --timeout 900
```

完了すると `https://dialectic-bizdoctor-xxxxx.asia-northeast1.run.app` のようなURLが表示される。

各指定の理由：

| 指定 | 理由 |
|---|---|
| `--source .` | Dockerfile を使って Cloud Build でイメージを作る |
| `--set-secrets` | APIキーを Secret Manager から環境変数として渡す |
| `--max-instances 1` | 分析回次のデータをコンテナ内に保存しているため、複数台に分かれると回次が食い違う |
| `--session-affinity` | Streamlit は接続を保ったまま動くため、同じ利用者を同じコンテナにつなぐ |
| `--timeout 900` | Gemini の読み取りに時間がかかる資料でも途中で切れないようにする |

## 3. 知っておくべき制約

- **データは消える。** Cloud Run のコンテナ内の書き込みは一時的で、コンテナが止まると失われる。介入や資料投入で作られた回次（`data/` 配下）は、再起動のたびに同梱のサンプル（第1次分析のみ）に戻る。デモには都合がよいが、実運用では Cloud Storage か Firestore への保存に切り替える必要がある。
- **アップロードは30MBまで。** Cloud Run のリクエスト上限（32MiB）に合わせて Dockerfile で制限している。
- **公開URLになる。** `--allow-unauthenticated` を付けると誰でも開ける。投入資料は Gemini API に送られ、APIの利用料も発生する。審査員への公開期間が終わったら、`--no-allow-unauthenticated` で再デプロイするか、サービスを削除する。

## 4. ローカルでの確認（任意）

Docker が入っていれば、Cloud Run と同じ形で手元で動かせる。

```powershell
docker build -t dialectic-bizdoctor .
docker run --rm -p 8080:8080 -e GEMINI_API_KEY=<キー> dialectic-bizdoctor
```

ブラウザで `http://localhost:8080` を開く。`-e GEMINI_API_KEY` を省くと、読み取りはモック動作になる。

## 5. 片付け

```powershell
gcloud run services delete dialectic-bizdoctor --region asia-northeast1
```
