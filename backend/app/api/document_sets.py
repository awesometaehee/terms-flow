import logging
import uuid
from collections.abc import Iterator
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ERROR_RESPONSES
from app.models import (
    DocumentFile,
    DocumentSetStatus,
    DocumentSetVersion,
    FileFormat,
    ProductRevision,
)
from app.rendering.html import render_combined_html
from app.rendering.loader import plan_from_manifest
from app.schemas.document_sets import (
    DocumentFileOut,
    DocumentSetDetail,
    DocumentSetManifest,
    DocumentSetSummary,
    PreviewOut,
    PreviewRequest,
    PublishRequest,
)
from app.services import document_sets
from app.storage import open_object
from app.tasks import defer_render

logger = logging.getLogger(__name__)
router = APIRouter(tags=["document sets"])
SessionDep = Annotated[Session, Depends(get_session)]

MEDIA_TYPES = {FileFormat.PDF: "application/pdf", FileFormat.PNG: "image/png"}


def _file_name(file: DocumentFile) -> str:
    return file.storage_key.rsplit("/", 1)[-1]


@router.post("/products/{product_id}/preview", responses=ERROR_RESPONSES)
def preview(product_id: uuid.UUID, data: PreviewRequest, session: SessionDep) -> PreviewOut:
    """3종 문서와 통합본 미리보기. 발행 버전은 만들지 않는다."""
    return document_sets.preview(session, product_id, data.excluded_clause_keys)


@router.post(
    "/products/{product_id}/document-sets",
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERROR_RESPONSES,
)
def publish(product_id: uuid.UUID, data: PublishRequest, session: SessionDep) -> DocumentSetSummary:
    """조합 결과를 고정한 PENDING 버전을 만들고 렌더링 작업을 넣는다.

    완료되면 버전 상태가 PUBLISHED(또는 FAILED)가 된다. GET /document-sets/{id}로 확인한다.
    """
    version = document_sets.request_publication(
        session, product_id, data.change_reason, data.excluded_clause_keys
    )
    session.commit()
    try:
        defer_render(version.id)
    except Exception:
        logger.exception("렌더링 작업 등록 실패: %s", version.id)
        version.status = DocumentSetStatus.FAILED
        version.failure_reason = "렌더링 작업을 큐에 넣지 못했습니다."
        session.commit()
    return DocumentSetSummary.model_validate(version)


def _detail(version: DocumentSetVersion) -> DocumentSetDetail:
    return DocumentSetDetail(
        id=version.id,
        product_id=version.product_id,
        version_no=version.version_no,
        status=version.status,
        change_reason=version.change_reason,
        batch_id=version.batch_id,
        created_at=version.created_at,
        published_at=version.published_at,
        failure_reason=version.failure_reason,
        manifest=DocumentSetManifest.model_validate(version.manifest),
        files=[
            DocumentFileOut(
                id=f.id,
                file_name=_file_name(f),
                document_type=f.document_type,
                format=f.format,
                page_no=f.page_no,
                sha256=f.sha256,
                size_bytes=f.size_bytes,
            )
            for f in version.files
        ],
    )


@router.post("/document-sets/{version_id}/retry", responses=ERROR_RESPONSES)
def retry(version_id: uuid.UUID, session: SessionDep) -> DocumentSetSummary:
    """실패한 버전을 같은 manifest로 다시 렌더링한다 (버전 번호는 그대로)."""
    version = document_sets.retry_failed_version(session, version_id)
    session.commit()
    defer_render(version.id)
    return DocumentSetSummary.model_validate(version)


@router.get("/document-sets/{version_id}", responses=ERROR_RESPONSES)
def get_document_set(version_id: uuid.UUID, session: SessionDep) -> DocumentSetDetail:
    return _detail(document_sets.get_document_set(session, version_id))


@router.get(
    "/document-sets/{version_id}/html", response_class=HTMLResponse, responses=ERROR_RESPONSES
)
def get_document_set_html(version_id: uuid.UUID, session: SessionDep) -> str:
    """manifest에 고정된 리비전으로 통합본 HTML을 다시 만든다 (현재 조항을 읽지 않는다)."""
    version = document_sets.get_document_set(session, version_id)
    revision = session.get(ProductRevision, version.product_revision_id)
    assert revision is not None
    manifest = DocumentSetManifest.model_validate(version.manifest)
    return render_combined_html(plan_from_manifest(session, manifest, revision.snapshot))


@router.get("/document-sets/{version_id}/files/{file_id}", responses=ERROR_RESPONSES)
def download_file(
    version_id: uuid.UUID, file_id: uuid.UUID, session: SessionDep
) -> StreamingResponse:
    file = document_sets.get_document_file(session, version_id, file_id)
    body = open_object(file.storage_key)

    def chunks() -> Iterator[bytes]:
        try:
            yield from iter(lambda: body.read(1024 * 1024), b"")
        finally:
            body.close()

    return StreamingResponse(
        chunks(),
        media_type=MEDIA_TYPES[file.format],
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(_file_name(file))}",
            "Content-Length": str(file.size_bytes),
            "X-Content-SHA256": file.sha256,
        },
    )
