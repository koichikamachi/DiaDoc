# DiaDoc（Dialectic-BizDoctor）— Cloud Run 用コンテナ（公開デモ）
#
# 方針：ステートレス。見本（C001 アルファ製菓・C002 架空の窮境企業）をイメージに焼き込み、
# ブラウザのセッションごとに一時フォルダへ複製して使う（DBD_SESSION_SANDBOX=1）。
# 審査員が同時に開いても論争・資料・SQLite の途中状態は混ざらず、再起動すれば見本の状態に戻る。
#
# graphviz について：意思決定ツリーは st.graphviz_chart で描き、レイアウトはブラウザ側（viz.js）で行う。
# サーバー側で dot コマンドは使わないので、OS の graphviz パッケージは入れない（Python の graphviz は DOT を組み立てるだけ）。

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    # Cloud Run の HTTP/1 リクエスト上限（32MiB）に合わせ、アップロードを30MBまでに制限する
    STREAMLIT_SERVER_MAX_UPLOAD_SIZE=30 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    # 見本（読み取り専用）と、セッションごとの作業場所
    DBD_DATA_DIR=/app/data \
    DBD_SESSION_SANDBOX=1 \
    DBD_SANDBOX_ROOT=/tmp

WORKDIR /app

# 依存関係：pyproject.toml の範囲で、constraints.txt の版に固定して入れる
# uv は既定ではキャッシュからハードリンクで部品を置き、キャッシュ（約1GB）もイメージに残す。
# ハードリンクの多いイメージは Cloud Run が読み込めない（Container import failed）ことがあるので、
# コピーで置き、キャッシュは残さない。最後に、ハードリンクが残っていないことを確かめる
COPY pyproject.toml constraints.txt ./
RUN pip install uv \
 && uv pip install --system --no-cache --link-mode=copy -r pyproject.toml -c constraints.txt \
 && pip uninstall -y uv \
 && test "$(find "$(python -c 'import site; print(site.getsitepackages()[0])')" -type f -links +1 | wc -l)" -eq 0

# アプリ本体と見本データ
COPY .streamlit ./.streamlit
COPY src ./src
COPY data ./data

# 日本語などのファイル名があると、Cloud Run がイメージを読み込めない（Container import failed）。
# 見本のファイル名は英数字にし、表示名は inputs/titles.json に書く。紛れ込んでいたら、ここでビルドを止める
RUN bad="$(find data src .streamlit | LC_ALL=C grep '[^ -~]' || true)"; \
    if [ -n "$bad" ]; then echo "ファイル名に英数字以外があります（titles.json で表示名を持たせてください）:"; echo "$bad"; exit 1; fi

# 念のため、見本に紛れ込んだ実行時ファイルを消す（.dockerignore でも除いている）
RUN find data \( -name 'checkpoints.sqlite*' -o -name 'debate_trace.jsonl' -o -name 'adjustments.json' -o -name '*.tmp' \) -delete

# root 以外で動かす。/app は root の持ち物のまま（見本を書き換えられない）。書き込みは /tmp の作業場所だけ
RUN useradd --create-home appuser
USER appuser

EXPOSE 8080

# $PORT は Cloud Run が与える（既定 8080）。WebSocket は Cloud Run がそのまま通す。
# CORS と XSRF の保護は Streamlit の既定（有効）のまま使う（画面と通信が同じ URL なので問題ない）
CMD ["sh", "-c", "exec streamlit run src/ui/app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true"]
