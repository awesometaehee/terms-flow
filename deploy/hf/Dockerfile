# Hugging Face Spaces(Docker) 임시 배포(현업 검토용).
# deploy/hf/assemble.sh가 이 파일을 Space 저장소 루트의 Dockerfile로 복사한다 (빌드 컨텍스트 = Space 루트).
# 화면 빌드 + API + 작업 처리(PDF·PNG 렌더러)를 한 컨테이너로 만든다. DB·파일은 Supabase에 둔다
# (Space의 디스크는 다시 시작하면 지워진다).

FROM node:24-bookworm-slim AS web
RUN npm install -g pnpm@12.10.1
WORKDIR /web
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.13-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TZ=Asia/Seoul \
    HOME=/home/user \
    PORT=7860 \
    STATIC_DIR=/app/web \
    STORAGE_BACKEND=s3 \
    S3_FORCE_PATH_STYLE=true
# Spaces는 컨테이너를 UID 1000 사용자로 실행한다.
RUN useradd -m -u 1000 user
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
# 렌더러: Chromium과 한글 글꼴(Noto CJK)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*
COPY backend/ ./
COPY schemas/ /schemas/
COPY --from=web /web/dist /app/web
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh && chown -R user:user /app
USER user
EXPOSE 7860
CMD ["/app/start.sh"]
