# terms-flow

KMS(지식 관리 시스템): 재사용 단락(모듈)을 골라 끌어서 조합하고 서식 편집기로 고쳐 문서를 만들고,
버전 관리·PDF/PNG 발행·공통 모듈 일괄 반영을 한다. 상품 데이터로 약관·약관 주요 내용·상품설명서를 만드는
상품 문서 기능도 함께 있다.

- 개발 가이드: [docs/약관·상품설명서 자동 생성 시스템 바이브코딩 개발 가이드.md](docs/약관·상품설명서%20자동%20생성%20시스템%20바이브코딩%20개발%20가이드.md)
- 구현 계획·결과: [docs/구현 계획.md](docs/구현%20계획.md)

**개발은 로컬, 운영은 Docker**: 개발할 때는 PC에 설치한 PostgreSQL과 `uv`·`pnpm`으로 직접 실행하고,
운영 서버에는 `docker-compose.yml`로 배포한다.

> 현업 검토용 무료 임시 배포(Hugging Face Spaces + Supabase)는 [DEPLOY.md](DEPLOY.md)를 따른다.

## 구성

| 경로 | 내용 |
|---|---|
| `backend/` | Python 3.13 · FastAPI API, Procrastinate worker(렌더러), Alembic 마이그레이션 |
| `frontend/` | React + Vite + Mantine |
| `schemas/` | 판매 구성·레이아웃 JSON Schema. 버전별 파일, 사용 후 수정 금지 |
| `data/` | 로컬 개발 파일 저장소 (`data/storage`, 테스트는 `data/storage-test`). 커밋하지 않는다 |

## 로컬 개발

### 1. 준비 (최초 1회)

필요한 것: PostgreSQL(17 이상), Node.js 24, [uv](https://docs.astral.sh/uv/), pnpm 12.

```powershell
py -m pip install --user uv==0.12.24      # uv. %APPDATA%\Python\Python3xx\Scripts를 PATH에 추가
npm install -g pnpm@12.10.1
```

로컬 PostgreSQL에 앱 사용자와 DB를 만든다. 시작 메뉴의 **SQL Shell (psql)**로 `postgres` 계정에 접속해 실행한다.
테스트가 `terms_flow_test` DB를 자동으로 만들 수 있도록 `CREATEDB` 권한을 준다.

```sql
CREATE ROLE terms_flow LOGIN CREATEDB PASSWORD '<비밀번호>';
CREATE DATABASE terms_flow OWNER terms_flow;
```

설정 파일을 만들고 `POSTGRES_PASSWORD`를 위 비밀번호로 바꾼다.

```powershell
copy .env.example .env
```

의존성을 설치하고 DB 스키마를 만든다.

```powershell
cd backend
uv sync                              # Python 3.13과 패키지 설치 (.venv)
uv run playwright install chromium   # PDF 렌더링용 Chromium
uv run alembic upgrade head          # DB 마이그레이션
cd ..\frontend
pnpm install
```

### 2. 실행 (터미널 3개)

```powershell
# 1) API  http://127.0.0.1:8000/docs
cd backend; uv run uvicorn app.main:app --reload --port 8000

# 2) worker (발행·일괄 수정 렌더링). 코드를 바꾸면 다시 실행한다.
cd backend; uv run python -m procrastinate --app=app.worker.queue_app worker

# 3) 화면  http://127.0.0.1:5173  (/api는 8000번으로 프록시)
cd frontend; pnpm dev
```

생성된 PDF·PNG는 `data/storage/document-sets/...`에 저장된다.
한글 글꼴은 Windows의 맑은 고딕을 쓴다 (운영 이미지는 Noto Sans CJK KR).

### 3. 테스트·검사

```powershell
cd backend
uv run pytest                              # 별도 DB terms_flow_test와 data/storage-test 사용
uv run ruff check .; uv run ruff format --check .
uv run mypy app migrations tests
uv run alembic revision --autogenerate -m "설명"   # 모델 변경 후 마이그레이션 생성

cd ..\frontend
pnpm typecheck; pnpm test
pnpm gen:api       # API 변경 후 타입 재생성 (로컬 API 실행 중일 때, src/api/schema.ts)
```

## 운영 배포 (Docker)

서버에 Docker(Compose 포함)를 설치하고 저장소를 받은 뒤 실행한다.

```sh
cp .env.production.example .env.production   # 비밀번호·키를 바꾼다
docker compose --env-file .env.production up -d --build
```

| 서비스 | 역할 |
|---|---|
| `db` | PostgreSQL 17 (외부 포트 없음, 볼륨 `pgdata`) |
| `storage` | SeaweedFS S3 호환 저장소 (외부 포트 없음, 볼륨 `storagedata`). 운영 저장소가 정해지면 외부 S3로 교체 |
| `migrate` | 시작 시 `alembic upgrade head` 후 종료 |
| `api` | FastAPI (외부 포트 없음) |
| `worker` | 렌더링 작업 처리 (Chromium·Noto CJK 포함) |
| `web` | nginx가 빌드된 화면을 제공하고 `/api`를 api로 넘긴다. `WEB_PORT`(기본 8080) |

의존성 버전은 `backend/uv.lock`, `frontend/pnpm-lock.yaml`과 이미지 태그로 고정한다. 공급망 위험을 줄이기 위해
배포 후 2주가 지나지 않은 패키지는 잠그지 않는다(`pyproject.toml`의 `exclude-newer`, `pnpm-workspace.yaml`의 `minimumReleaseAge`).
