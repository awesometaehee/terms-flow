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
from app.models import DocumentSetStatus, DocumentStatus, FileFormat, Publication
from app.rendering import kms as kms_render
from app.schemas.catalog import ClauseRevisionOut
from app.schemas.kms import (
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    DocumentCreate,
    DocumentDetail,
    DocumentRevisionDetail,
    DocumentRevisionSummary,
    DocumentSave,
    DocumentStatusChange,
    DocumentSummary,
    PromoteBlock,
    PublicationDetail,
    PublicationFileOut,
    PublicationSummary,
    PublishDocument,
    SearchOut,
    TagOut,
    VariableCreate,
    VariableOut,
    VariableUpdate,
)
from app.services import catalog, documents, publications, search, taxonomy
from app.storage import open_object
from app.tasks import defer_publication

logger = logging.getLogger(__name__)
router = APIRouter(tags=["KMS"])
SessionDep = Annotated[Session, Depends(get_session)]
MEDIA_TYPES = {FileFormat.PDF: "application/pdf", FileFormat.PNG: "image/png"}


# --- 카테고리·태그·변수 -------------------------------------------------------------


@router.get("/categories")
def list_categories(session: SessionDep) -> list[CategoryOut]:
    return [CategoryOut.model_validate(c) for c in taxonomy.list_categories(session)]


@router.post("/categories", status_code=status.HTTP_201_CREATED, responses=ERROR_RESPONSES)
def create_category(data: CategoryCreate, session: SessionDep) -> CategoryOut:
    category = taxonomy.create_category(session, data)
    session.commit()
    return CategoryOut.model_validate(category)


@router.patch("/categories/{category_id}", responses=ERROR_RESPONSES)
def update_category(
    category_id: uuid.UUID, data: CategoryUpdate, session: SessionDep
) -> CategoryOut:
    category = taxonomy.update_category(session, category_id, data)
    session.commit()
    return CategoryOut.model_validate(category)


@router.delete(
    "/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERROR_RESPONSES
)
def delete_category(category_id: uuid.UUID, session: SessionDep) -> None:
    taxonomy.delete_category(session, category_id)
    session.commit()


@router.get("/tags")
def list_tags(session: SessionDep) -> list[TagOut]:
    return taxonomy.list_tags(session)


@router.get("/variables")
def list_variables(session: SessionDep) -> list[VariableOut]:
    return [VariableOut.model_validate(v) for v in taxonomy.list_variables(session)]


@router.post("/variables", status_code=status.HTTP_201_CREATED, responses=ERROR_RESPONSES)
def create_variable(data: VariableCreate, session: SessionDep) -> VariableOut:
    variable = taxonomy.create_variable(session, data)
    session.commit()
    return VariableOut.model_validate(variable)


@router.patch("/variables/{variable_id}", responses=ERROR_RESPONSES)
def update_variable(
    variable_id: uuid.UUID, data: VariableUpdate, session: SessionDep
) -> VariableOut:
    variable = taxonomy.update_variable(session, variable_id, data)
    session.commit()
    return VariableOut.model_validate(variable)


@router.delete(
    "/variables/{variable_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERROR_RESPONSES
)
def delete_variable(variable_id: uuid.UUID, session: SessionDep) -> None:
    """어디에서도 쓰지 않는 변수만 지울 수 있다."""
    taxonomy.delete_variable(session, variable_id)
    session.commit()


@router.get("/search")
def search_all(q: str, session: SessionDep) -> SearchOut:
    """모듈·문서 제목과 본문 부분 일치 검색."""
    return search.search(session, q)


# --- 문서 --------------------------------------------------------------------------


@router.get("/documents")
def list_documents(
    session: SessionDep,
    status: DocumentStatus | None = None,
    category_id: uuid.UUID | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[DocumentSummary]:
    return documents.list_documents(session, status=status, category_id=category_id, tag=tag, q=q)


@router.post("/documents", status_code=status.HTTP_201_CREATED, responses=ERROR_RESPONSES)
def create_document(data: DocumentCreate, session: SessionDep) -> DocumentDetail:
    document = documents.create_document(session, data)
    session.commit()
    return documents.to_detail(session, documents.get_document(session, document.id))


@router.get("/documents/{document_id}", responses=ERROR_RESPONSES)
def get_document(document_id: uuid.UUID, session: SessionDep) -> DocumentDetail:
    return documents.to_detail(session, documents.get_document(session, document_id))


@router.delete(
    "/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERROR_RESPONSES
)
def delete_document(document_id: uuid.UUID, session: SessionDep) -> None:
    """작성 중·사용 중 문서를 삭제한다. 종료 문서는 409 DOCUMENT_ENDED."""
    documents.delete_document(session, document_id)
    session.commit()


@router.put("/documents/{document_id}", responses=ERROR_RESPONSES)
def save_document(
    document_id: uuid.UUID, data: DocumentSave, session: SessionDep
) -> DocumentDetail:
    """문서 전체(제목·분류·변수 값·단락 목록)를 저장하고 새 리비전을 남긴다."""
    documents.save_document(session, document_id, data)
    session.commit()
    session.expire_all()
    return documents.to_detail(session, documents.get_document(session, document_id))


@router.post("/documents/{document_id}/status", responses=ERROR_RESPONSES)
def change_status(
    document_id: uuid.UUID, data: DocumentStatusChange, session: SessionDep
) -> DocumentDetail:
    documents.change_status(session, document_id, data)
    session.commit()
    return documents.to_detail(session, documents.get_document(session, document_id))


@router.post(
    "/documents/{document_id}/blocks/{block_id}/promote",
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def promote_block(
    document_id: uuid.UUID, block_id: uuid.UUID, data: PromoteBlock, session: SessionDep
) -> ClauseRevisionOut:
    """문서에서 고친 모듈 단락을 원본 모듈의 새 리비전으로 저장한다."""
    revision = documents.promote_block(session, document_id, block_id, data)
    session.commit()
    return catalog.revision_out(revision)


@router.get("/documents/{document_id}/revisions", responses=ERROR_RESPONSES)
def list_revisions(document_id: uuid.UUID, session: SessionDep) -> list[DocumentRevisionSummary]:
    rows = documents.list_revisions(session, document_id)
    return [DocumentRevisionSummary.model_validate(r) for r in rows]


@router.get("/documents/{document_id}/revisions/{revision_no}", responses=ERROR_RESPONSES)
def get_revision(
    document_id: uuid.UUID, revision_no: int, session: SessionDep
) -> DocumentRevisionDetail:
    return DocumentRevisionDetail.model_validate(
        documents.get_revision(session, document_id, revision_no)
    )


@router.get(
    "/documents/{document_id}/preview", response_class=HTMLResponse, responses=ERROR_RESPONSES
)
def preview(document_id: uuid.UUID, session: SessionDep, revision_no: int | None = None) -> str:
    """저장된 문서(또는 지정 리비전)의 출력 미리보기 HTML."""
    revision = (
        documents.get_revision(session, document_id, revision_no)
        if revision_no is not None
        else documents.latest_revision(session, document_id)
    )
    return kms_render.render_html(revision.snapshot, preview=True)


# --- 발행본 ------------------------------------------------------------------------


def _publication_summary(publication: Publication) -> PublicationSummary:
    return PublicationSummary(
        id=publication.id,
        version_no=publication.version_no,
        status=publication.status,
        change_reason=publication.change_reason,
        batch_id=publication.batch_id,
        revision_no=publication.revision.revision_no,
        renderer_version=publication.renderer_version,
        failure_reason=publication.failure_reason,
        created_at=publication.created_at,
        published_at=publication.published_at,
    )


def _defer(publication: Publication, session: Session) -> None:
    try:
        defer_publication(publication.id)
    except Exception:
        logger.exception("렌더링 작업 등록 실패: %s", publication.id)
        publication.status = DocumentSetStatus.FAILED
        publication.failure_reason = "렌더링 작업을 큐에 넣지 못했습니다."
        session.commit()


@router.post(
    "/documents/{document_id}/publications",
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERROR_RESPONSES,
)
def publish(
    document_id: uuid.UUID, data: PublishDocument, session: SessionDep
) -> PublicationSummary:
    """저장된 최신 리비전으로 PDF·PNG 발행을 요청한다."""
    publication = publications.request_publication(session, document_id, data.change_reason)
    session.commit()
    _defer(publication, session)
    return _publication_summary(publication)


@router.get("/documents/{document_id}/publications", responses=ERROR_RESPONSES)
def list_publications(document_id: uuid.UUID, session: SessionDep) -> list[PublicationSummary]:
    return [_publication_summary(p) for p in publications.list_publications(session, document_id)]


def _file_name(storage_key: str) -> str:
    return storage_key.rsplit("/", 1)[-1]


@router.get("/publications/{publication_id}", responses=ERROR_RESPONSES)
def get_publication(publication_id: uuid.UUID, session: SessionDep) -> PublicationDetail:
    publication = publications.get_publication(session, publication_id)
    return PublicationDetail(
        **_publication_summary(publication).model_dump(),
        document_id=publication.document_id,
        files=[
            PublicationFileOut(
                id=f.id,
                file_name=_file_name(f.storage_key),
                format=f.format,
                page_no=f.page_no,
                sha256=f.sha256,
                size_bytes=f.size_bytes,
            )
            for f in publication.files
        ],
    )


@router.post("/publications/{publication_id}/retry", responses=ERROR_RESPONSES)
def retry_publication(publication_id: uuid.UUID, session: SessionDep) -> PublicationSummary:
    publication = publications.retry_failed(session, publication_id)
    session.commit()
    _defer(publication, session)
    return _publication_summary(publication)


@router.get("/publications/{publication_id}/files/{file_id}", responses=ERROR_RESPONSES)
def download(
    publication_id: uuid.UUID, file_id: uuid.UUID, session: SessionDep
) -> StreamingResponse:
    file = publications.get_file(session, publication_id, file_id)
    file_name = _file_name(file.storage_key)
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
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(file_name)}",
            "Content-Length": str(file.size_bytes),
            "X-Content-SHA256": file.sha256,
        },
    )
