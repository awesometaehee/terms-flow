"""DB에서 조합 입력을 읽는다.

- plan_latest: 새 미리보기·발행용. 상품에 맞는 ACTIVE 템플릿의 최신 리비전과
  조항 최신 리비전을 쓴다.
- plan_from_manifest: 발행된(또는 발행 중인) 버전 재현용. manifest에 고정된 리비전 ID만 읽고
  최신 조항을 다시 조회하지 않는다.
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, selectinload

from app.errors import FieldError
from app.models import (
    ClauseRevision,
    DocumentType,
    Template,
    TemplateClauseRule,
    TemplateRevision,
    TemplateStatus,
)
from app.rendering.composer import (
    DOCUMENT_ORDER,
    ClauseDecision,
    ClauseInput,
    CompositionFailed,
    DocumentPlan,
    RuleInput,
    SetPlan,
    TemplateInput,
    compose_set,
)
from app.rendering.rules import evaluate_condition
from app.schemas.document_sets import (
    DocumentSetManifest,
    ManifestClause,
    ManifestDocument,
    ManifestExcludedClause,
)


def _latest_clause_revisions(
    session: Session, clause_ids: set[uuid.UUID]
) -> dict[uuid.UUID, ClauseRevision]:
    if not clause_ids:
        return {}
    latest = (
        sa.select(ClauseRevision.clause_id, sa.func.max(ClauseRevision.revision_no).label("no"))
        .where(ClauseRevision.clause_id.in_(clause_ids))
        .group_by(ClauseRevision.clause_id)
        .subquery()
    )
    rows = session.scalars(
        sa.select(ClauseRevision).join(
            latest,
            sa.and_(
                ClauseRevision.clause_id == latest.c.clause_id,
                ClauseRevision.revision_no == latest.c.no,
            ),
        )
    ).all()
    return {r.clause_id: r for r in rows}


def _select_templates(
    session: Session, product: Mapping[str, Any]
) -> dict[DocumentType, tuple[Template, TemplateRevision]]:
    templates = session.scalars(
        sa.select(Template)
        .where(Template.status == TemplateStatus.ACTIVE)
        .options(
            selectinload(Template.revisions)
            .selectinload(TemplateRevision.clause_rules)
            .joinedload(TemplateClauseRule.clause)
        )
        .order_by(Template.template_key)
    ).all()
    selected: dict[DocumentType, tuple[Template, TemplateRevision]] = {}
    errors: list[FieldError] = []
    for document_type in DOCUMENT_ORDER:
        candidates = [
            (t, t.revisions[-1])
            for t in templates
            if t.document_type == document_type
            and evaluate_condition(t.revisions[-1].selection_condition, product)[0]
        ]
        path = f"templates.{document_type.value}"
        if not candidates:
            errors.append(FieldError(path=path, message="이 상품에 적용할 템플릿이 없습니다."))
        elif len(candidates) > 1:
            keys = ", ".join(t.template_key for t, _ in candidates)
            errors.append(
                FieldError(path=path, message=f"적용 가능한 템플릿이 여러 개입니다: {keys}")
            )
        else:
            selected[document_type] = candidates[0]
    if errors:
        raise CompositionFailed(errors)
    return selected


def plan_latest(
    session: Session, snapshot: Mapping[str, Any], excluded_keys: Sequence[str] = ()
) -> SetPlan:
    selected = _select_templates(session, snapshot["product"])
    clause_ids = {rule.clause_id for _, rev in selected.values() for rule in rev.clause_rules}
    revisions = _latest_clause_revisions(session, clause_ids)
    inputs: dict[DocumentType, TemplateInput] = {}
    for document_type, (template, revision) in selected.items():
        rules = []
        for rule in revision.clause_rules:
            clause_rev = revisions[rule.clause_id]
            rules.append(
                RuleInput(
                    clause=ClauseInput(
                        clause_key=rule.clause.clause_key,
                        title=rule.clause.title,
                        clause_revision_id=clause_rev.id,
                        revision_no=clause_rev.revision_no,
                        content=clause_rev.content,
                        rich=clause_rev.rich,
                    ),
                    condition=rule.condition,
                    sort_order=rule.sort_order,
                    required=rule.required,
                )
            )
        inputs[document_type] = TemplateInput(
            document_type=document_type,
            template_key=template.template_key,
            template_revision_id=revision.id,
            revision_no=revision.revision_no,
            layout=revision.layout_definition,
            rules=tuple(rules),
        )
    return compose_set(inputs, snapshot, excluded_keys)


def manifest_documents(plan: SetPlan) -> list[ManifestDocument]:
    documents = []
    for doc in plan.documents:
        included = [d for d in doc.decisions if d.included]
        documents.append(
            ManifestDocument(
                document_type=doc.document_type,
                template_key=doc.template.template_key,
                template_revision_id=doc.template.template_revision_id,
                template_revision_no=doc.template.revision_no,
                clauses=[
                    ManifestClause(
                        clause_key=d.clause_key,
                        title=d.title,
                        clause_revision_id=d.clause.clause_revision_id,
                        revision_no=d.clause.revision_no,
                        order=i,
                        required=d.required,
                        reason=d.reason,
                    )
                    for i, d in enumerate(included, start=1)
                ],
                excluded_clauses=[
                    ManifestExcludedClause(
                        clause_key=d.clause_key,
                        title=d.title,
                        clause_revision_id=d.clause.clause_revision_id,
                        revision_no=d.clause.revision_no,
                        required=d.required,
                        reason=d.reason,
                    )
                    for d in doc.decisions
                    if not d.included
                ],
            )
        )
    return documents


def plan_from_manifest(
    session: Session, manifest: DocumentSetManifest, snapshot: Mapping[str, Any]
) -> SetPlan:
    template_ids = {d.template_revision_id for d in manifest.documents}
    clause_ids = {c.clause_revision_id for d in manifest.documents for c in d.clauses} | {
        c.clause_revision_id for d in manifest.documents for c in d.excluded_clauses
    }
    templates = {
        r.id: r
        for r in session.scalars(
            sa.select(TemplateRevision).where(TemplateRevision.id.in_(template_ids))
        ).all()
    }
    clauses = {
        r.id: r
        for r in session.scalars(
            sa.select(ClauseRevision).where(ClauseRevision.id.in_(clause_ids))
        ).all()
    }

    def clause_input(key: str, title: str, revision_id: uuid.UUID) -> ClauseInput:
        rev = clauses[revision_id]
        return ClauseInput(
            clause_key=key,
            title=title,
            clause_revision_id=rev.id,
            revision_no=rev.revision_no,
            content=rev.content,
            rich=rev.rich,
        )

    documents = []
    for doc in manifest.documents:
        template_rev = templates[doc.template_revision_id]
        decisions = [
            ClauseDecision(
                clause_key=c.clause_key,
                title=c.title,
                required=c.required,
                included=True,
                reason=c.reason,
                clause=clause_input(c.clause_key, c.title, c.clause_revision_id),
            )
            for c in sorted(doc.clauses, key=lambda c: c.order)
        ] + [
            ClauseDecision(
                clause_key=c.clause_key,
                title=c.title,
                required=c.required,
                included=False,
                reason=c.reason,
                clause=clause_input(c.clause_key, c.title, c.clause_revision_id),
            )
            for c in doc.excluded_clauses
        ]
        documents.append(
            DocumentPlan(
                template=TemplateInput(
                    document_type=doc.document_type,
                    template_key=doc.template_key,
                    template_revision_id=template_rev.id,
                    revision_no=template_rev.revision_no,
                    layout=template_rev.layout_definition,
                ),
                decisions=tuple(decisions),
            )
        )
    return SetPlan(snapshot=snapshot, documents=tuple(documents))
