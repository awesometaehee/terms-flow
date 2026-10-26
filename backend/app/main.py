from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.access import AccessControl
from app.api import (
    assets,
    bulk_updates,
    catalog,
    document_sets,
    drafts,
    health,
    images,
    imports,
    kms,
    products,
)
from app.config import get_settings
from app.errors import install_error_handlers
from app.storage import ensure_bucket


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await run_in_threadpool(ensure_bucket)
    yield


app = FastAPI(title="KMS API (템플릿·문서·상품 문서)", lifespan=lifespan)
install_error_handlers(app)
for module in (
    health,
    kms,
    catalog,
    products,
    document_sets,
    bulk_updates,
    assets,
    imports,
    drafts,
    images,
):
    app.include_router(module.router, prefix="/api")

# --- 임시 배포(검토용) 설정. 환경변수가 없으면 모두 꺼진다 (로컬 개발 기본) ---
_settings = get_settings()
if _settings.cors_origins:
    # 화면을 API와 다른 주소에서 띄울 때만 필요하다 (같은 주소면 쓰지 않는다).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
# 접근 제한은 가장 바깥에서 먼저 확인한다.
app.add_middleware(AccessControl, settings=_settings)
if _settings.static_dir and _settings.static_dir.is_dir():
    # 빌드한 화면. 화면 주소는 #/... (hash router)라 index.html 하나로 충분하다.
    # /api/*는 위 라우터가 먼저 받는다.
    app.mount("/", StaticFiles(directory=_settings.static_dir, html=True), name="web")
