"""문서 세트 미리보기·발행 요청·조회.

발행 요청은 API에서 조합까지 끝내 manifest에 템플릿·조항 리비전을 고정하고 PENDING 버전을 만든다.
렌더링과 PUBLISHED 전환은 worker(app.rendering.publisher)가 한다.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session, selectinload

from app.errors import CompositionError, ConflictError, NotFoundError
from app.models import DocumentFile, DocumentSetStatus, DocumentSetVersion
from app.rendering.composer import (
    DOCUMENT_LABELS,
    USER_EXCLUDED_REASON,
    CompositionFailed,
    SetPlan,
)
from app.rendering.html import render_combined_html, render_document_html
from app.rendering.loader import manifest_documents, plan_latest
from app.schemas.document_sets import (
    ClauseDecisionOut,
    DocumentSetManifest,
    ManifestDocument,
    PreviewDocumentOut,
    PreviewOut,
)
from app.services.products import ensure_not_ended, get_product, latest_revision


def _plan(
    session: Session, product_id: uuid.UUID, excluded_keys: Sequence[str]
) -> tuple[SetPlan, int]:
    product = get_product(session, product_id, for_update=True)
    ensure_not_ended(product)
    revision = latest_revision(session, product.id)
    try:
        return plan_latest(session, revision.snapshot, excluded_keys), revision.revision_no
    except CompositionFailed as exc:
        raise CompositionError(exc.errors) from exc


def preview(session: Session, product_id: uuid.UUID, excluded_keys: Sequence[str]) -> PreviewOut:
    """발행 없이 3종 문서와 통합본 HTML, 조항 포함·제외 결정을 돌려준다."""
    plan, revision_no = _plan(session, product_id, excluded_keys)
    documents = []
    for doc in plan.documents:
        order = 0
        decisions = []
        for d in doc.decisions:
            order += d.included
            decisions.append(
                ClauseDecisionOut(
                    clause_key=d.clause_key,
                    title=d.title,
                    revision_no=d.clause.revision_no,
                    required=d.required,
                    included=d.included,
                    order=order if d.included else None,
                    reason=d.reason,
                )
            )
        documents.append(
            PreviewDocumentOut(
                document_type=doc.document_type,
                label=DOCUMENT_LABELS[doc.document_type],
                template_key=doc.template.template_key,
                template_revision_no=doc.template.revision_no,
                clauses=decisions,
                html=render_document_html(plan, doc, preview=True),
            )
        )
    return PreviewOut(
        product_revision_no=revision_no,
        documents=documents,
        combined_html=render_combined_html(plan, preview=True),
    )


def reserve_document_set_version(
    session: Session,
    product_id: uuid.UUID,
    change_reason: str,
    documents: Sequence[ManifestDocument] = (),
    batch_id: uuid.UUID | None = None,
) -> DocumentSetVersion:
    """현재 상품 버전과 조합 결과를 고정한 새 PENDING 문서 세트 버전을 만든다. ENDED는 거부."""
    product = get_product(session, product_id, for_update=True)
    ensure_not_ended(product)
    revision = latest_revision(session, product.id)
    last_no = session.scalar(
        sa.select(sa.func.max(DocumentSetVersion.version_no)).where(
            DocumentSetVersion.product_id == product.id
        )
    )
    manifest = DocumentSetManifest(
        product_revision_id=revision.id,
        product_revision_no=revision.revision_no,
        documents=list(documents),
    )
    version = DocumentSetVersion(
        product_id=product.id,
        version_no=(last_no or 0) + 1,
        product_revision_id=revision.id,
        manifest=manifest.model_dump(mode="json"),
        status=DocumentSetStatus.PENDING,
        change_reason=change_reason,
        batch_id=batch_id,
    )
    session.add(version)
    session.flush()
    return version


def request_publication(
    session: Session,
    product_id: uuid.UUID,
    change_reason: str,
    excluded_keys: Sequence[str],
    batch_id: uuid.UUID | None = None,
) -> DocumentSetVersion:
    plan, _ = _plan(session, product_id, excluded_keys)
    return reserve_document_set_version(
        session, product_id, change_reason, documents=manifest_documents(plan), batch_id=batch_id
    )


def latest_published(session: Session, product_id: uuid.UUID) -> DocumentSetVersion | None:
    return session.scalar(
        sa.select(DocumentSetVersion)
        .where(
            DocumentSetVersion.product_id == product_id,
            DocumentSetVersion.status == DocumentSetStatus.PUBLISHED,
        )
        .order_by(DocumentSetVersion.version_no.desc())
        .limit(1)
    )


def user_excluded_keys(version: DocumentSetVersion | None) -> list[str]:
    """이전 발행본에서 사용자가 뺀 선택 조항. 재발행할 때 그대로 유지한다."""
    if version is None:
        return []
    manifest = DocumentSetManifest.model_validate(version.manifest)
    return [
        c.clause_key
        for d in manifest.documents
        for c in d.excluded_clauses
        if c.reason == USER_EXCLUDED_REASON
    ]


def retry_failed_version(session: Session, version_id: uuid.UUID) -> DocumentSetVersion:
    """FAILED 버전을 같은 manifest로 다시 렌더링하도록 PENDING으로 되돌린다.

    새 버전 번호를 쓰지 않으므로 재시도로 버전이 중복되지 않는다.
    """
    version = session.scalar(
        sa.select(DocumentSetVersion).where(DocumentSetVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise NotFoundError("문서 세트 버전을 찾을 수 없습니다.")
    if version.status != DocumentSetStatus.FAILED:
        raise ConflictError("실패한 버전만 다시 시도할 수 있습니다.", code="NOT_FAILED")
    ensure_not_ended(get_product(session, version.product_id, for_update=True))
    version.status = DocumentSetStatus.PENDING
    version.failure_reason = None
    session.flush()
    return version


def list_document_sets(session: Session, product_id: uuid.UUID) -> Sequence[DocumentSetVersion]:
    get_product(session, product_id)
    return session.scalars(
        sa.select(DocumentSetVersion)
        .where(DocumentSetVersion.product_id == product_id)
        .order_by(DocumentSetVersion.version_no.desc())
    ).all()


def get_document_set(session: Session, version_id: uuid.UUID) -> DocumentSetVersion:
    version = session.scalar(
        sa.select(DocumentSetVersion)
        .where(DocumentSetVersion.id == version_id)
        .options(selectinload(DocumentSetVersion.files))
    )
    if version is None:
        raise NotFoundError("문서 세트 버전을 찾을 수 없습니다.")
    return version


def get_document_file(session: Session, version_id: uuid.UUID, file_id: uuid.UUID) -> DocumentFile:
    file = session.scalar(
        sa.select(DocumentFile).where(
            DocumentFile.id == file_id, DocumentFile.document_set_version_id == version_id
        )
    )
    if file is None:
        raise NotFoundError("파일을 찾을 수 없습니다.")
    return file
