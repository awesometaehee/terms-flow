"""모듈·문서 통합 검색. 제목과 본문을 부분 일치로 찾는다 (pg_trgm 색인)."""

import sqlalchemy as sa
from sqlalchemy.orm import Session, selectinload

from app.db import like_pattern
from app.models import Clause, ClauseRevision, Document
from app.schemas.kms import SearchHit, SearchOut

DOCUMENT_STATUS_LABELS = {"DRAFT": "작성 중", "ACTIVE": "사용 중", "ENDED": "종료"}


def _excerpt(text: str, query: str, width: int = 120) -> str:
    flat = " ".join(text.split())
    pos = flat.lower().find(query.lower())
    if pos < 0:
        return flat[:width]
    start = max(0, pos - width // 3)
    snippet = flat[start : start + width]
    return ("…" if start else "") + snippet + ("…" if start + width < len(flat) else "")


def search(session: Session, q: str, limit: int = 50) -> SearchOut:
    query = q.strip()
    if not query:
        return SearchOut(query=q)
    pattern = like_pattern(query)

    latest = (
        sa.select(ClauseRevision.clause_id, sa.func.max(ClauseRevision.revision_no).label("no"))
        .group_by(ClauseRevision.clause_id)
        .subquery()
    )
    module_rows = session.execute(
        sa.select(Clause, ClauseRevision.content)
        .join(latest, latest.c.clause_id == Clause.id)
        .join(
            ClauseRevision,
            sa.and_(
                ClauseRevision.clause_id == Clause.id, ClauseRevision.revision_no == latest.c.no
            ),
        )
        .where(
            Clause.deleted_at.is_(None),
            sa.or_(Clause.title.ilike(pattern), ClauseRevision.content.ilike(pattern)),
        )
        .options(selectinload(Clause.tags))
        .order_by(Clause.title)
        .limit(limit)
    ).all()
    hits = [
        SearchHit(
            kind="MODULE",
            id=clause.id,
            title=clause.title,
            subtitle=f"템플릿 · {clause.clause_key}",
            excerpt=_excerpt(content, query),
            tags=[t.name for t in clause.tags],
            category_id=clause.category_id,
        )
        for clause, content in module_rows
    ]
    documents = session.scalars(
        sa.select(Document)
        .where(
            Document.deleted_at.is_(None),
            sa.or_(Document.title.ilike(pattern), Document.search_text.ilike(pattern)),
        )
        .options(selectinload(Document.tags))
        .order_by(Document.updated_at.desc())
        .limit(limit)
    ).all()
    hits += [
        SearchHit(
            kind="DOCUMENT",
            id=d.id,
            title=d.title,
            subtitle=f"문서 · {DOCUMENT_STATUS_LABELS[d.status.value]}",
            excerpt=_excerpt(d.search_text, query),
            tags=[t.name for t in d.tags],
            category_id=d.category_id,
        )
        for d in documents
    ]
    return SearchOut(query=q, hits=hits)
