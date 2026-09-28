# Dialectic-BizDoctor — Cloud Run 用コンテナ
# Streamlit を $PORT（Cloud Run が与える。既定 8080）で起動する。

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    # Cloud Run の HTTP/1 リクエスト上限（32MiB）に合わせ、アップロードを30MBまでに制限する
    STREAMLIT_SERVER_MAX_UPLOAD_SIZE=30 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    DBD_DATA_DIR=/app/data

WORKDIR /app

# 依存関係（pyproject.toml を唯一の定義元とする）
COPY pyproject.toml ./
RUN pip install uv && uv pip install --system -r pyproject.toml

# アプリ本体とサンプルデータ
COPY .streamlit ./.streamlit
COPY src ./src
COPY data ./data

# root 以外で動かす
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8080

CMD ["sh", "-c", "streamlit run src/ui/app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true"]
