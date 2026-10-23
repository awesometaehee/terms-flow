"""KMS 문서 발행본(PDF·PNG).

발행 요청은 문서의 최신 리비전을 고정한 PENDING 발행본을 만들고,
worker가 렌더링해 PUBLISHED로 바꾼다.
변수 값이 비어 있으면(기본값도 없으면) 발행하지 않는다.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, FieldError, NotFoundError, ValidationFailed
from app.models import DocumentSetStatus, Publication, PublicationFile
from app.rendering.kms import missing_variables
from app.services.documents import ensure_not_ended, get_document, latest_revision


def request_publication(
    session: Session,
    document_id: uuid.UUID,
    change_reason: str,
    batch_id: uuid.UUID | None = None,
) -> Publication:
    document = get_document(session, document_id, for_update=True)
    ensure_not_ended(document)
    revision = latest_revision(session, document.id)
    if not revision.snapshot["blocks"]:
        raise ValidationFailed(
            [FieldError(path="blocks", message="단락이 없는 문서는 발행할 수 없습니다.")]
        )
    missing = missing_variables(revision.snapshot)
    if missing:
        labels = revision.snapshot["variables"]
        raise ValidationFailed(
            [
                FieldError(
                    path=f"variable_values.{k}", message=f"{labels[k]['label']} 값을 입력하세요."
                )
                for k in missing
            ]
        )
    last_no = session.scalar(
        sa.select(sa.func.max(Publication.version_no)).where(Publication.document_id == document.id)
    )
    publication = Publication(
        document_id=document.id,
        version_no=(last_no or 0) + 1,
        document_revision_id=revision.id,
        status=DocumentSetStatus.PENDING,
        change_reason=change_reason,
        batch_id=batch_id,
    )
    session.add(publication)
    session.flush()
    return publication


def list_publications(session: Session, document_id: uuid.UUID) -> Sequence[Publication]:
    get_document(session, document_id)
    return session.scalars(
        sa.select(Publication)
        .where(Publication.document_id == document_id)
        .order_by(Publication.version_no.desc())
    ).all()


def get_publication(session: Session, publication_id: uuid.UUID) -> Publication:
    publication = session.scalar(
        sa.select(Publication)
        .where(Publication.id == publication_id)
        .options(selectinload(Publication.files))
    )
    if publication is None:
        raise NotFoundError("발행본을 찾을 수 없습니다.")
    return publication


def get_file(session: Session, publication_id: uuid.UUID, file_id: uuid.UUID) -> PublicationFile:
    file = session.scalar(
        sa.select(PublicationFile).where(
            PublicationFile.id == file_id, PublicationFile.publication_id == publication_id
        )
    )
    if file is None:
        raise NotFoundError("파일을 찾을 수 없습니다.")
    return file


def retry_failed(session: Session, publication_id: uuid.UUID) -> Publication:
    """실패한 발행본을 같은 리비전으로 다시 렌더링하도록 되돌린다 (버전 번호는 그대로)."""
    publication = session.scalar(
        sa.select(Publication)
        .where(Publication.id == publication_id)
        .with_for_update(of=Publication)
    )
    if publication is None:
        raise NotFoundError("발행본을 찾을 수 없습니다.")
    if publication.status != DocumentSetStatus.FAILED:
        raise ConflictError("실패한 발행본만 다시 시도할 수 있습니다.", code="NOT_FAILED")
    ensure_not_ended(get_document(session, publication.document_id, for_update=True))
    publication.status = DocumentSetStatus.PENDING
    publication.failure_reason = None
    session.flush()
    return publication
