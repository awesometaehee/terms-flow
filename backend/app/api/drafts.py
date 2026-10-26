"""자동 임시저장본 API.

값은 화면의 편집 상태 그대로 보관하고 검증하지 않는다 (실제 저장할 때 검증한다).
"""

from datetime import datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Path, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ERROR_RESPONSES, FieldError, NotFoundError, ValidationFailed
from app.models import Draft
from app.schemas.common import RequestModel

router = APIRouter(tags=["drafts"])
SessionDep = Annotated[Session, Depends(get_session)]
KEY_PATTERN = r"^(module|document|module-new):[0-9a-f-]{32,36}$"
DraftKey = Annotated[str, Path(pattern=KEY_PATTERN)]
MAX_BYTES = 5 * 1024 * 1024


class DraftIn(RequestModel):
    base: str = Field(max_length=50)
    value: dict[str, Any]
    title: str | None = Field(default=None, max_length=200)


class DraftOut(BaseModel):
    key: str
    base: str
    value: dict[str, Any]
    title: str | None
    updated_at: datetime


class DraftSummary(BaseModel):
    key: str
    title: str | None
    updated_at: datetime


def _out(draft: Draft) -> DraftOut:
    return DraftOut(
        key=draft.key,
        base=draft.base,
        value=draft.value,
        title=draft.title,
        updated_at=draft.updated_at,
    )


@router.get("/drafts")
def list_drafts(
    session: SessionDep, prefix: Annotated[str, Field(pattern=r"^[a-z-]+:$")] = "module-new:"
) -> list[DraftSummary]:
    """새 모듈처럼 대상이 없는 임시본 목록 (최근 것부터)."""
    rows = session.scalars(
        sa.select(Draft).where(Draft.key.startswith(prefix)).order_by(Draft.updated_at.desc())
    ).all()
    return [DraftSummary(key=d.key, title=d.title, updated_at=d.updated_at) for d in rows]


@router.get("/drafts/{key}", responses=ERROR_RESPONSES)
def get_draft(key: DraftKey, session: SessionDep) -> DraftOut:
    draft = session.get(Draft, key)
    if draft is None:
        raise NotFoundError("임시저장본이 없습니다.")
    return _out(draft)


@router.put("/drafts/{key}", responses=ERROR_RESPONSES)
def put_draft(key: DraftKey, data: DraftIn, request: Request, session: SessionDep) -> DraftOut:
    """임시본을 덮어쓴다 (없으면 만든다). 탭을 닫을 때 보내는 요청도 같은 주소를 쓴다."""
    if int(request.headers.get("content-length") or 0) > MAX_BYTES:
        raise ValidationFailed(
            [FieldError(path="value", message="임시저장본이 너무 큽니다 (5MB).")]
        )
    draft = session.get(Draft, key)
    if draft is None:
        draft = Draft(key=key, base=data.base, value=data.value, title=data.title)
        session.add(draft)
    else:
        draft.base, draft.value, draft.title = data.base, data.value, data.title
        draft.updated_at = sa.func.now()
    session.commit()
    session.refresh(draft)
    return _out(draft)


@router.delete("/drafts/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(key: DraftKey, session: SessionDep) -> None:
    """임시본을 지운다 (없어도 성공)."""
    session.execute(sa.delete(Draft).where(Draft.key == key))
    session.commit()
