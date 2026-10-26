#!/usr/bin/env bash
# Hugging Face Space 시작: DB 구조 맞추기 → (비어 있으면) 가상 데이터 → API(화면 포함)와 worker 실행.
# Spaces에는 '배포 전 명령'이 없어 시작할 때 한다. 둘 중 하나가 멈추면 컨테이너를 끝내 Space가 다시 시작하게 한다.
set -uo pipefail

echo "[start] DB 구조를 최신으로 맞춥니다"
alembic upgrade head || { echo "[start] 마이그레이션 실패 — DATABASE_URL을 확인하세요"; exit 1; }

if [ "${SEED_DEMO_DATA:-true}" = "true" ]; then
    python -m app.demo_seed --if-empty || exit 1
fi

procrastinate --app=app.worker.queue_app worker &
worker=$!

# --proxy-headers: Space 프록시 뒤의 실제 접속 IP를 받는다 (ALLOWED_IPS 확인용).
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}" \
    --proxy-headers --forwarded-allow-ips '*' &
api=$!

trap 'kill -TERM "$worker" "$api" 2>/dev/null' TERM INT
wait -n "$worker" "$api"
status=$?
kill -TERM "$worker" "$api" 2>/dev/null
wait
exit "$status"
