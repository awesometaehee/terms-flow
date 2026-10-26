from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool

from app.api import (
    assets,
    bulk_updates,
    catalog,
    document_sets,
    drafts,
    health,
    imports,
    kms,
    products,
)
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
):
    app.include_router(module.router, prefix="/api")
