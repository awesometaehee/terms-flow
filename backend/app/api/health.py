from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_session
from app.storage import check_storage

router = APIRouter(tags=["health"])

CheckResult = Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: CheckResult
    database: CheckResult
    storage: CheckResult


@router.get("/health")
def health(response: Response, session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
    database: CheckResult = "ok"
    storage: CheckResult = "ok"
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        database = "error"
    try:
        check_storage()
    except Exception:
        storage = "error"

    overall: CheckResult = "ok" if database == storage == "ok" else "error"
    if overall == "error":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status=overall, database=database, storage=storage)
