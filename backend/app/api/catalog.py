import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ERROR_RESPONSES
from app.models import DocumentType
from app.schemas.catalog import (
    ClauseCreate,
    ClauseDetail,
    ClauseRevisionCreate,
    ClauseRevisionOut,
    ClauseSummary,
    ClauseUpdate,
    TemplateCreate,
    TemplateDetail,
    TemplateRevisionCreate,
    TemplateSummary,
)
from app.services import catalog

router = APIRouter(tags=["templates & clauses"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/clauses", status_code=status.HTTP_201_CREATED, responses=ERROR_RESPONSES)
def create_clause(data: ClauseCreate, session: SessionDep) -> ClauseDetail:
    clause = catalog.create_clause(session, data)
    session.commit()
    return catalog.clause_detail(session, clause.id)


@router.get("/clauses")
def list_clauses(
    session: SessionDep,
    document_type: DocumentType | None = None,
    category_id: uuid.UUID | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[ClauseSummary]:
    """모듈 목록. 카테고리(하위 포함)·태그·검색어로 거른다."""
    return catalog.list_clauses(session, document_type, category_id, tag, q)


@router.patch("/clauses/{clause_id}", responses=ERROR_RESPONSES)
def update_clause(clause_id: uuid.UUID, data: ClauseUpdate, session: SessionDep) -> ClauseDetail:
    """모듈 제목·카테고리·태그 변경 (본문은 새 리비전으로만 바꾼다)."""
    catalog.update_clause(session, clause_id, data)
    session.commit()
    return catalog.clause_detail(session, clause_id)


@router.delete(
    "/clauses/{clause_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERROR_RESPONSES
)
def delete_clause(clause_id: uuid.UUID, session: SessionDep) -> None:
    """작성 중·사용 중 문서에서 쓰지 않는 모듈만 삭제한다. 쓰는 곳이 있으면 409 CLAUSE_IN_USE."""
    catalog.delete_clause(session, clause_id)
    session.commit()


@router.get("/clauses/{clause_id}", responses=ERROR_RESPONSES)
def get_clause(clause_id: uuid.UUID, session: SessionDep) -> ClauseDetail:
    return catalog.clause_detail(session, clause_id)


@router.post(
    "/clauses/{clause_id}/revisions", status_code=status.HTTP_201_CREATED, responses=ERROR_RESPONSES
)
def add_clause_revision(
    clause_id: uuid.UUID, data: ClauseRevisionCreate, session: SessionDep
) -> ClauseRevisionOut:
    revision = catalog.add_clause_revision(session, clause_id, data)
    session.commit()
    return catalog.revision_out(revision)


@router.post("/templates", status_code=status.HTTP_201_CREATED, responses=ERROR_RESPONSES)
def create_template(data: TemplateCreate, session: SessionDep) -> TemplateDetail:
    template = catalog.create_template(session, data)
    session.commit()
    return catalog.template_detail(session, template.id)


@router.get("/templates")
def list_templates(
    session: SessionDep, document_type: DocumentType | None = None
) -> list[TemplateSummary]:
    return catalog.list_templates(session, document_type)


@router.get("/templates/{template_id}", responses=ERROR_RESPONSES)
def get_template(template_id: uuid.UUID, session: SessionDep) -> TemplateDetail:
    return catalog.template_detail(session, template_id)


@router.post(
    "/templates/{template_id}/revisions",
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def add_template_revision(
    template_id: uuid.UUID, data: TemplateRevisionCreate, session: SessionDep
) -> TemplateDetail:
    catalog.add_template_revision(session, template_id, data)
    session.commit()
    session.expire_all()
    return catalog.template_detail(session, template_id)
