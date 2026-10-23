# 빌드 컨텍스트는 저장소 루트다 (schemas/를 함께 복사하기 위해).
FROM python:3.13-slim-bookworm AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/ ./
COPY schemas/ /schemas/

FROM base AS api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

# 렌더러: Chromium(Playwright)과 한글 글꼴(Noto CJK)을 이미지에 고정한다. PNG 변환은 pypdfium2.
FROM base AS worker
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*
CMD ["procrastinate", "--app=app.worker.queue_app", "worker"]
