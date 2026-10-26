#!/usr/bin/env bash
# Hugging Face Space에 올릴 파일을 한 폴더에 모은다 (GitHub Actions와 수동 배포가 같이 쓴다).
#   사용: bash deploy/hf/assemble.sh <출력 폴더>
# 커밋된 파일만 담는다 (git archive). .env·data·node_modules 같은 로컬 파일은 들어가지 않는다.
set -euo pipefail

out="${1:?출력 폴더를 지정하세요}"
root="$(git rev-parse --show-toplevel)"
rm -rf "$out"
mkdir -p "$out"

git -C "$root" archive HEAD backend frontend schemas | tar -x -C "$out"
rm -rf "$out/backend/tests" "$out/frontend/tsconfig.tsbuildinfo"

cp "$root/deploy/hf/Dockerfile" "$out/Dockerfile"
cp "$root/deploy/hf/start.sh" "$out/start.sh"
cp "$root/deploy/hf/space-readme.md" "$out/README.md"
printf '%s\n' "frontend/node_modules" "frontend/dist" "**/__pycache__" > "$out/.dockerignore"

echo "Space 파일을 모았습니다: $out"
