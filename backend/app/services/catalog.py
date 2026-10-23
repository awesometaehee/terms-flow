"""조항·템플릿과 그 불변 버전.

리비전은 수정하지 않고 항상 새 번호로 추가한다. 리비전 추가 요청은 base_revision_no가
현재 최신 번호와 같아야 한다 (다른 사람이 먼저 새 리비전을 만들었으면 409).
"""

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, selectinload

from app.db import like_pattern
from app.errors import ConflictError, FieldError, NotFoundError, ValidationFailed
from app.models import (
    Clause,
    ClauseRevision,
    Document,
    DocumentBlock,
    DocumentStatus,
    DocumentType,
    Tag,
    Template,
    TemplateClauseRule,
    TemplateRevision,
)
from app.rendering.rules import validate_condition, validate_layout
from app.schemas.catalog import (
    ClauseCreate,
    ClauseDetail,
    ClauseRevisionCreate,
    ClauseRevisionOut,
    ClauseRuleIn,
    ClauseRuleOut,
    ClauseSummary,
    ClauseUpdate,
    TemplateCreate,
    TemplateDetail,
    TemplateRevisionCreate,
    TemplateRevisionOut,
    TemplateSummary,
)
from app.services.taxonomy import (
    category_and_descendants,
    name_list,
    require_category,
    resolve_tags,
    validate_body,
)


def _check_base_revision(latest_no: int, base_revision_no: int) -> None:
    if latest_no != base_revision_no:
        raise ConflictError(
            f"최신 리비전은 {latest_no}번입니다. 최신 내용을 다시 조회한 뒤 수정하세요.",
            code="VERSION_CONFLICT",
        )


# --- 조항 ---------------------------------------------------------------------


def _get_clause(session: Session, clause_id: uuid.UUID, *, for_update: bool = False) -> Clause:
    stmt = (
        sa.select(Clause)
        .where(Clause.id == clause_id)
        .options(selectinload(Clause.revisions), selectinload(Clause.tags))
    )
    if for_update:
        stmt = stmt.with_for_update(of=Clause)
    clause = session.scalar(stmt)
    if clause is None:
        raise NotFoundError("조항을 찾을 수 없습니다.")
    return clause


def create_clause(session: Session, data: ClauseCreate) -> Clause:
    content, content_json = validate_body(session, data.content, data.content_json)
    require_category(session, data.category_id)
    if session.scalar(sa.select(Clause.id).where(Clause.clause_key == data.clause_key)):
        raise ConflictError("이미 존재하는 모듈 키입니다.", code="DUPLICATE_CLAUSE_KEY")
    clause = Clause(
        clause_key=data.clause_key,
        document_type=data.document_type,
        kind=data.kind,
        title=data.title,
        category_id=data.category_id,
        tags=resolve_tags(session, data.tags),
        revisions=[
            ClauseRevision(
                revision_no=1,
                content=content,
                content_json=content_json,
                change_reason=data.change_reason,
            )
        ],
    )
    session.add(clause)
    session.flush()
    return clause


def _ensure_not_deleted(clause: Clause) -> None:
    if clause.deleted_at is not None:
        raise ConflictError("삭제된 모듈은 고칠 수 없습니다.", code="CLAUSE_DELETED")


def update_clause(session: Session, clause_id: uuid.UUID, data: ClauseUpdate) -> Clause:
    clause = _get_clause(session, clause_id, for_update=True)
    _ensure_not_deleted(clause)
    if data.title is not None:
        clause.title = data.title
    if data.clear_category:
        clause.category_id = None
    elif data.category_id is not None:
        require_category(session, data.category_id)
        clause.category_id = data.category_id
    if data.tags is not None:
        clause.tags = resolve_tags(session, data.tags)
    session.flush()
    return clause


def add_clause_revision(
    session: Session, clause_id: uuid.UUID, data: ClauseRevisionCreate
) -> ClauseRevision:
    content, content_json = validate_body(session, data.content, data.content_json)
    clause = _get_clause(session, clause_id, for_update=True)
    _ensure_not_deleted(clause)
    latest_no = clause.revisions[-1].revision_no
    _check_base_revision(latest_no, data.base_revision_no)
    revision = ClauseRevision(
        clause_id=clause.id,
        revision_no=latest_no + 1,
        content=content,
        content_json=content_json,
        change_reason=data.change_reason,
    )
    session.add(revision)
    session.flush()
    return revision


def delete_clause(session: Session, clause_id: uuid.UUID) -> None:
    """작성 중·사용 중 문서와 상품 템플릿에서 쓰지 않는 모듈만 삭제한다.

    종료 문서·문서 리비전·발행본·일괄 작업 이력이 참조하므로 행은 남기고 숨긴다.
    """
    clause = _get_clause(session, clause_id, for_update=True)
    if clause.deleted_at is not None:
        return
    documents = session.scalars(
        sa.select(Document.title)
        .where(
            Document.status != DocumentStatus.ENDED,
            Document.deleted_at.is_(None),
            Document.blocks.any(DocumentBlock.clause_id == clause.id),
        )
        .order_by(Document.title)
    ).all()
    if documents:
        raise ConflictError(
            f"문서 {len(documents)}개({name_list(documents)})에서 쓰고 있어 지울 수 없습니다. "
            "문서에서 이 모듈 단락을 먼저 빼세요.",
            code="CLAUSE_IN_USE",
        )
    if session.scalar(sa.select(sa.func.count()).where(TemplateClauseRule.clause_id == clause.id)):
        raise ConflictError(
            "상품 문서 템플릿에서 쓰고 있어 지울 수 없습니다.", code="CLAUSE_IN_USE"
        )
    clause.deleted_at = sa.func.now()
    session.flush()


def revision_out(revision: ClauseRevision) -> ClauseRevisionOut:
    return ClauseRevisionOut(
        id=revision.id,
        revision_no=revision.revision_no,
        content=revision.content,
        content_json=revision.rich,
        change_reason=revision.change_reason,
        created_at=revision.created_at,
    )


def clause_detail(session: Session, clause_id: uuid.UUID) -> ClauseDetail:
    clause = _get_clause(session, clause_id)
    return ClauseDetail(
        **_clause_summary(clause).model_dump(),
        revisions=[revision_out(r) for r in clause.revisions],
    )


def _clause_summary(clause: Clause) -> ClauseSummary:
    latest = clause.revisions[-1]
    excerpt = " ".join(latest.content.split())
    return ClauseSummary(
        id=clause.id,
        clause_key=clause.clause_key,
        document_type=clause.document_type,
        kind=clause.kind,
        title=clause.title,
        category_id=clause.category_id,
        tags=[t.name for t in clause.tags],
        latest_revision_no=latest.revision_no,
        excerpt=excerpt[:160],
        deleted=clause.deleted_at is not None,
        updated_at=latest.created_at,
    )


def list_clauses(
    session: Session,
    document_type: DocumentType | None = None,
    category_id: uuid.UUID | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[ClauseSummary]:
    stmt = (
        sa.select(Clause)
        .where(Clause.deleted_at.is_(None))
        .options(selectinload(Clause.revisions), selectinload(Clause.tags))
        .order_by(Clause.title, Clause.clause_key)
    )
    if document_type is not None:
        stmt = stmt.where(Clause.document_type == document_type)
    if category_id is not None:
        stmt = stmt.where(Clause.category_id.in_(category_and_descendants(session, category_id)))
    if tag:
        stmt = stmt.where(Clause.tags.any(Tag.name == tag))
    if q:
        pattern = like_pattern(q)
        latest_content = (
            sa.select(ClauseRevision.clause_id)
            .where(ClauseRevision.content.ilike(pattern))
            .scalar_subquery()
        )
        stmt = stmt.where(
            sa.or_(
                Clause.title.ilike(pattern),
                Clause.clause_key.ilike(pattern),
                Clause.id.in_(latest_content),
            )
        )
    return [_clause_summary(c) for c in session.scalars(stmt).all()]


# --- 템플릿 -------------------------------------------------------------------


def _get_template(
    session: Session, template_id: uuid.UUID, *, for_update: bool = False
) -> Template:
    stmt = (
        sa.select(Template)
        .where(Template.id == template_id)
        .options(
            selectinload(Template.revisions)
            .selectinload(TemplateRevision.clause_rules)
            .joinedload(TemplateClauseRule.clause)
        )
    )
    if for_update:
        stmt = stmt.with_for_update(of=Template)
    template = session.scalar(stmt)
    if template is None:
        raise NotFoundError("템플릿을 찾을 수 없습니다.")
    return template


def _build_rules(
    session: Session,
    document_type: DocumentType,
    rules: Sequence[ClauseRuleIn],
    layout: dict[str, Any],
    selection_condition: dict[str, Any],
) -> list[TemplateClauseRule]:
    """레이아웃·선택 조건·조항 규칙을 함께 검증하고 규칙 행을 만든다."""
    keys = {r.clause_key for r in rules}
    clauses = {
        c.clause_key: c
        for c in session.scalars(
            sa.select(Clause).where(Clause.clause_key.in_(keys), Clause.deleted_at.is_(None))
        ).all()
    }
    errors = validate_layout(layout)
    errors += validate_condition(selection_condition, "selection_condition")
    seen: set[str] = set()
    built: list[TemplateClauseRule] = []
    for i, rule in enumerate(rules):
        errors += validate_condition(rule.condition, f"clause_rules[{i}].condition")
        path = f"clause_rules[{i}].clause_key"
        clause = clauses.get(rule.clause_key)
        if rule.clause_key in seen:
            errors.append(FieldError(path=path, message="같은 조항이 중복됩니다."))
        elif clause is None:
            errors.append(FieldError(path=path, message="존재하지 않는 조항입니다."))
        elif clause.document_type not in (None, document_type):
            errors.append(FieldError(path=path, message="템플릿과 문서 종류가 다른 조항입니다."))
        else:
            built.append(
                TemplateClauseRule(
                    clause_id=clause.id,
                    condition=rule.condition,
                    sort_order=rule.sort_order,
                    required=rule.required,
                )
            )
        seen.add(rule.clause_key)
    if errors:
        raise ValidationFailed(errors)
    return built


def create_template(session: Session, data: TemplateCreate) -> Template:
    if session.scalar(sa.select(Template.id).where(Template.template_key == data.template_key)):
        raise ConflictError("이미 존재하는 템플릿 키입니다.", code="DUPLICATE_TEMPLATE_KEY")
    rules = _build_rules(
        session,
        data.document_type,
        data.clause_rules,
        data.layout_definition,
        data.selection_condition,
    )
    template = Template(
        template_key=data.template_key,
        document_type=data.document_type,
        name=data.name,
        revisions=[
            TemplateRevision(
                revision_no=1,
                layout_definition=data.layout_definition,
                selection_condition=data.selection_condition,
                change_reason=data.change_reason,
                clause_rules=rules,
            )
        ],
    )
    session.add(template)
    session.flush()
    return template


def add_template_revision(
    session: Session, template_id: uuid.UUID, data: TemplateRevisionCreate
) -> TemplateRevision:
    template = _get_template(session, template_id, for_update=True)
    latest_no = template.revisions[-1].revision_no
    _check_base_revision(latest_no, data.base_revision_no)
    revision = TemplateRevision(
        template_id=template.id,
        revision_no=latest_no + 1,
        layout_definition=data.layout_definition,
        selection_condition=data.selection_condition,
        change_reason=data.change_reason,
        clause_rules=_build_rules(
            session,
            template.document_type,
            data.clause_rules,
            data.layout_definition,
            data.selection_condition,
        ),
    )
    session.add(revision)
    session.flush()
    return revision


def _template_summary(template: Template) -> TemplateSummary:
    return TemplateSummary(
        id=template.id,
        template_key=template.template_key,
        document_type=template.document_type,
        name=template.name,
        status=template.status,
        latest_revision_no=template.revisions[-1].revision_no,
    )


def _revision_out(revision: TemplateRevision) -> TemplateRevisionOut:
    return TemplateRevisionOut(
        id=revision.id,
        revision_no=revision.revision_no,
        layout_definition=revision.layout_definition,
        selection_condition=revision.selection_condition,
        change_reason=revision.change_reason,
        created_at=revision.created_at,
        clause_rules=[
            ClauseRuleOut(
                clause_id=rule.clause_id,
                clause_key=rule.clause.clause_key,
                condition=rule.condition,
                sort_order=rule.sort_order,
                required=rule.required,
            )
            for rule in revision.clause_rules
        ],
    )


def template_detail(session: Session, template_id: uuid.UUID) -> TemplateDetail:
    template = _get_template(session, template_id)
    return TemplateDetail(
        **_template_summary(template).model_dump(),
        revisions=[_revision_out(r) for r in template.revisions],
    )


def list_templates(
    session: Session, document_type: DocumentType | None = None
) -> list[TemplateSummary]:
    stmt = (
        sa.select(Template)
        .options(selectinload(Template.revisions))
        .order_by(Template.template_key)
    )
    if document_type is not None:
        stmt = stmt.where(Template.document_type == document_type)
    return [_template_summary(t) for t in session.scalars(stmt).all()]
