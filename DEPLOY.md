# 무료 임시 배포 — Hugging Face Spaces + Supabase (현업 검토용)

현업이 화면을 직접 써 보고 확인할 수 있도록 **무료 서비스로 임시** 배포하는 방법과, 검토가 끝난 뒤 **모두 지우는** 방법이다.
운영 배포(docker compose)는 [README](README.md)를 따른다.

> **실제 고객 정보·실제 약관 원문을 올리지 않는다.** 검토는 가상 데이터(`[샘플]`)로 한다.
> 계정·Space·Supabase 프로젝트 만들기와 첫 배포는 담당자 승인 후 진행한다.

---

## 1. 구성

```
     검토자 브라우저 ── https://<사용자>-<space>.hf.space
                         │  HTTP Basic 로그인 (검토용 계정), 선택: 허용 IP
                         ▼
 ┌─ Hugging Face Space (Docker, 무료 CPU) ─────────────┐
 │  화면 (React 빌드 결과, / )                          │
 │  API (FastAPI, /api/*)                               │
 │  작업 처리 worker (PDF·PNG 렌더러, Chromium)          │
 └───────────────┬───────────────────┬─────────────────┘
                 │ DATABASE_URL      │ S3 API
 ┌─ Supabase (무료) ─────────────────────────────────────┐
 │  PostgreSQL (데이터, 작업 큐)   Storage 버킷 (이미지·PDF) │
 └──────────────────────────────────────────────────────┘
       GitHub main push ──(GitHub Actions)──▶ Space 저장소 ──▶ 자동 빌드
```

| 구성 요소 | 내용 |
|---|---|
| 화면 | React + Vite 빌드 결과를 API가 같은 주소에서 제공한다. 화면 주소는 `#/…`(hash router)라 경로 설정이 필요 없다. |
| API 주소·CORS | 화면이 `/api`를 같은 주소로 부르므로 API 주소 설정·CORS가 필요 없다 (다른 주소에서 띄울 때만 `CORS_ORIGINS`). |
| worker | 발행(PDF·PNG)·일괄 반영 작업. API와 같은 컨테이너에서 실행한다 (`deploy/hf/start.sh`). |
| DB | Supabase PostgreSQL. `DATABASE_URL`(Session pooler)로 연결한다. 컨테이너가 시작할 때 `alembic upgrade head`로 구조를 맞춘다. |
| 파일 | Supabase Storage(S3 호환) 버킷. Space의 디스크는 다시 시작하면 지워지므로 파일을 Space에 두지 않는다. |
| 접근 제한 | 모든 화면·API에 HTTP Basic 로그인 (`BASIC_AUTH_USERS`). `/api/health`만 열어 둔다. 선택: 허용 IP (`ALLOWED_IPS`). 검색 엔진 수집 막기 (`X-Robots-Tag: noindex`). |
| 가상 데이터 | DB가 비어 있으면 시작할 때 `[샘플]` 치환 항목 5개·템플릿 4개·문서 2개를 넣는다 (`backend/app/demo_seed.py`). |

설정 파일

| 파일 | 역할 |
|---|---|
| `deploy/hf/Dockerfile` | 화면 빌드 → API·worker·Chromium·한글 글꼴 이미지 (UID 1000, 포트 7860) |
| `deploy/hf/start.sh` | 마이그레이션 → 가상 데이터(비어 있을 때) → API와 worker 실행 |
| `deploy/hf/space-readme.md` | Space 설정(`sdk: docker`, `app_port: 7860`)과 안내 |
| `deploy/hf/assemble.sh` | Space에 올릴 파일 모으기 (커밋된 `backend/`·`frontend/`·`schemas/` + 위 파일) |
| `deploy/hf/variables.example` | Space에 넣을 환경변수 예시 (실제 값 없음) |
| `.github/workflows/deploy-hf-space.yml` | `main` push 시 Space로 자동 배포 |

---

## 2. 무료 조건과 제약 (진행 전 확인)

무료 정책은 바뀔 수 있다. 진행 전에 각 서비스의 현재 조건을 다시 확인한다.

| 서비스 | 무료로 쓰는 것 | 제약 |
|---|---|---|
| Hugging Face Spaces | CPU basic 하드웨어 (Docker Space) | 한동안 접속이 없으면 잠든다. 다시 열면 1~2분 깨어난다. 디스크는 다시 시작하면 지워진다. **공개 Space는 코드(Space 저장소)가 공개된다** (데이터·비밀 값은 공개되지 않는다). |
| Supabase | PostgreSQL, Storage (프로젝트 2개까지) | DB·저장 용량 한도가 있다. **일주일 넘게 쓰지 않으면 프로젝트가 일시 정지**된다 (대시보드에서 다시 켬). |
| GitHub Actions | 자동 배포 실행 시간 | 비공개 저장소는 월 무료 시간 한도 안에서 쓴다 (배포 1회에 1분 안팎). |

**카드 등록 없이** 위 무료 범위만 쓴다. 유료 하드웨어·업그레이드는 선택하지 않는다.

Space 공개 여부

- **공개 Space (이 프로젝트의 결정, 2026-10-26)**: 검토자는 주소와 검토용 계정만 있으면 된다. Space 저장소의 코드가 공개되는 것만 감수한다.
- **비공개 Space**: 코드가 공개되지 않는다. 대신 검토자마다 Hugging Face 계정이 있어야 하고 Space(조직)에 초대해야 한다.

---

## 3. 배포 절차

### 3-1. Supabase (DB·파일)

1. https://supabase.com 가입 → **New project**. 지역은 **Northeast Asia (Seoul)**, DB 비밀번호는 새로 만들어 따로 보관한다.
2. **DB 주소** — 프로젝트 → **Connect** → **Session pooler**(포트 5432) 주소를 복사하고 끝에 `?sslmode=require`를 붙인다.
   (Direct connection은 IPv6 전용이라 Space에서 연결되지 않을 수 있다. Transaction pooler(6543)는 이 앱과 맞지 않는다.)
3. **파일 버킷** — **Storage** → **New bucket** → 이름 `kms-review`, **Public 끄기(비공개)**.
4. **S3 키** — **Storage** → **S3 Connection**에서 Endpoint·Region을 확인하고 **New access key**로 키를 만든다.

### 3-2. Hugging Face Space (앱)

1. https://huggingface.co 가입 → **New Space** → SDK **Docker**(Blank) → 하드웨어 **CPU basic (free)** → 공개 여부 선택(2장).
2. **Settings** → **Variables and secrets**에 `deploy/hf/variables.example`대로 넣는다.
   - Secret: `DATABASE_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `BASIC_AUTH_USERS`
   - Variable: `S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`, (선택) `ALLOWED_IPS`, `SEED_DEMO_DATA`
3. **쓰기 토큰** — https://huggingface.co/settings/tokens → **Fine-grained** 토큰, 이 Space에만 **write** 권한.

### 3-3. GitHub 자동 배포 연결

1. GitHub 저장소 → **Settings** → **Secrets and variables** → **Actions**
   - **Variables**: `HF_SPACE` = `<HF 사용자 또는 조직>/<Space 이름>`
   - **Secrets**: `HF_TOKEN` = 3-2의 토큰
2. **Actions** 탭 → **Deploy to Hugging Face Space** → **Run workflow** (첫 배포). 이후에는 `main`에 앱 코드가 바뀐 push가 있을 때마다 자동으로 배포된다.
3. Space 화면의 **Logs**에서 진행을 본다.
   - Build: 화면 빌드 + Chromium 설치 (첫 빌드 10분 안팎)
   - Container: `[start] DB 구조를 최신으로 맞춥니다` → `가상 데이터를 넣었습니다 …` (DB가 비어 있을 때) → `Uvicorn running on http://0.0.0.0:7860`

### 3-4. 확인

- **앱 주소 `https://<사용자>-<space>.hf.space` 를 직접 연다.** (Space 소개 페이지 안의 미리보기 창에서는 로그인 창이 막힐 수 있다.)
- 로그인 창 → 검토용 계정으로 로그인
- 문서·템플릿·치환 항목·이미지 메뉴에 `[샘플]` 데이터가 보인다
- `[샘플] 헤리티지 100 이용약관` → **발행 (PDF·PNG)** → 발행 탭에서 PDF 내려받기 (worker·Storage 동작 확인)
- 이미지 메뉴에서 이미지를 올린 뒤 Space를 **Restart**해도 남아 있다 (Storage 확인)
- `https://<사용자>-<space>.hf.space/api/health` 가 `{"status":"ok","database":"ok","storage":"ok"}`

---

## 4. 테스트 계정

- 형식: `BASIC_AUTH_USERS=아이디:비밀번호,아이디2:비밀번호2` (아이디·비밀번호에 `,` `:` 은 쓰지 않는다)
- 비밀번호는 매번 새로 만든다. 예:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(12))"
  ```
- 검토자마다 계정을 따로 주면 나중에 한 명만 빼기 쉽다 (그 항목만 지우고 저장 → Space가 다시 시작).
- 계정·비밀번호는 **Space Secret에만** 넣는다. 저장소·문서·채팅방에 그대로 남기지 말고 검토자에게 개별로 전달한다.
- 브라우저가 로그인 정보를 기억한다. 비밀번호를 바꾼 뒤에는 브라우저를 모두 닫았다가 다시 연다.

---

## 5. 자동 배포 운영

- `main`에 `backend/`, `frontend/`, `schemas/`, `deploy/hf/`가 바뀐 push가 있을 때만 배포한다. 문서만 고친 push는 배포하지 않는다.
- `HF_SPACE`가 비어 있으면 워크플로는 건너뛴다 (설정 전·삭제 후에도 실패 알림이 오지 않는다).
- Space 저장소는 배포 결과물이라 매번 덮어쓴다. Space에서 직접 고치지 않는다.
- 되돌리기: GitHub에서 이전 커밋으로 되돌려 push하거나, Actions에서 원하는 커밋으로 **Run workflow**. DB 구조가 바뀐 배포는 되돌려도 DB는 그대로이므로 주의한다.
- 검토 중 화면이 수시로 바뀌는 것이 싫으면 워크플로의 `branches: [main]`을 검토용 브랜치(예: `review`)로 바꾼다.

---

## 6. 삭제 절차 (검토 종료 후)

1. **데이터 확인** — 검토 의견이 문서·템플릿에 남아 있으면 먼저 PDF로 받거나 내용을 옮긴다. 삭제하면 되돌릴 수 없다.
2. **자동 배포 끄기** — GitHub → Settings → Secrets and variables → Actions에서 `HF_SPACE` 변수와 `HF_TOKEN` 시크릿을 지운다.
3. **Space 삭제** — Space → **Settings** → 맨 아래 **Delete this Space**.
4. **토큰 삭제** — https://huggingface.co/settings/tokens 에서 배포용 토큰을 **Delete**.
5. **Supabase 프로젝트 삭제** — 프로젝트 → **Project Settings** → **General** → **Delete project** (DB·Storage·키가 함께 지워진다).
6. **확인** — 앱 주소가 열리지 않는지, Supabase 프로젝트 목록과 Hugging Face Space 목록에서 사라졌는지 본다.
7. **계정 정리** — 검토용 비밀번호·DB 비밀번호를 적어 둔 곳이 있으면 지운다. 필요 없으면 이 배포용으로 만든 Hugging Face·Supabase 계정도 탈퇴한다.

---

## 7. 보안 메모

- 비밀번호·DB 주소·저장소 키는 Space Secret과 GitHub Secret에만 둔다. `.env`는 커밋하지 않는다 (`.gitignore`).
- Space에는 **커밋된** `backend/`·`frontend/`·`schemas/`만 올라간다 (`deploy/hf/assemble.sh`, `git archive`). 로컬 파일(`.env`, `data/`)·테스트 코드·Git 백업 폴더는 올라가지 않는다.
- Supabase 버킷은 비공개로 두고, 파일은 앱(로그인 필요)을 통해서만 보인다. DB는 Supabase 비밀번호 없이는 접속할 수 없다.
- 가상 데이터는 모두 `[샘플]` 표시가 붙은 꾸민 값이다 (회사·상품·전화번호 포함).
- HTTP Basic은 HTTPS(Hugging Face 기본) 위에서만 쓴다.
- 로그인이 없는 시스템이라 검토자 구분은 계정 이름으로만 한다. 자동 임시저장은 사람별이 아니라 문서별이다.
- 저장소에 예전 Git 백업 폴더(`terms-flow/.git-backup/`)가 들어 있다. 비밀 정보는 없고 배포에는 포함되지 않지만, 저장소에서도 지우는 것을 권한다.

## 8. 한계

- 컨테이너 1개로 실행한다. 동시에 많은 사람이 발행하면 PDF가 차례로 만들어진다.
- Space가 잠들어 있으면 첫 접속이 1~2분 걸린다. 깨어나는 동안 진행 중이던 작업은 다시 시작할 때 이어서 처리된다 (작업 큐가 DB에 있다).
- 가상 데이터는 DB가 비어 있을 때만 들어간다. 처음 상태로 되돌리려면 Supabase에서 DB를 비우고(또는 프로젝트를 새로 만들고) Space를 다시 시작한다.
