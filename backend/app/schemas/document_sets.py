"""문서 세트 버전과 manifest.

manifest는 발행 시점에 사용한 상품 버전·템플릿 버전·조항 버전과 순서, 렌더러 버전, 출력 파일을
고정한다. 과거 버전 조회·재현은 항상 manifest를 기준으로 하고 현재 최신 데이터를 다시 읽지 않는다.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models import DocumentSetStatus, DocumentType, FileFormat, OutputDocumentType
from app.schemas.common import Key, NonBlankStr, RequestModel, ResponseModel


class ManifestClause(BaseModel):
    """문서에 포함된 조항. order는 문서 안의 출력 순서(1부터)."""

    clause_key: str
    title: str
    clause_revision_id: uuid.UUID
    revision_no: int
    order: int
    required: bool
    reason: str


class ManifestExcludedClause(BaseModel):
    """템플릿 규칙에는 있지만 이 버전에서 제외된 조항과 사유."""

    clause_key: str
    title: str
    clause_revision_id: uuid.UUID
    revision_no: int
    required: bool
    reason: str


class ManifestDocument(BaseModel):
    document_type: DocumentType
    template_key: str
    template_revision_id: uuid.UUID
    template_revision_no: int
    clauses: list[ManifestClause]
    excluded_clauses: list[ManifestExcludedClause] = []


class ManifestFile(BaseModel):
    document_type: OutputDocumentType
    format: FileFormat
    page_no: int | None
    storage_key: str
    sha256: str


class DocumentSetManifest(BaseModel):
    schema_version: Literal[1] = 1
    product_revision_id: uuid.UUID
    product_revision_no: int
    # documents는 발행 요청 시(조합 결과), renderer_version·files는 렌더링 완료 시 채운다.
    documents: list[ManifestDocument] = []
    renderer_version: str | None = None
    files: list[ManifestFile] = []


class PreviewRequest(RequestModel):
    # 조건이 맞아도 이번 문서에서 뺄 선택 조항(required=False). 필수 조항은 뺄 수 없다.
    excluded_clause_keys: list[Key] = []


class PublishRequest(PreviewRequest):
    change_reason: NonBlankStr


class ClauseDecisionOut(BaseModel):
    clause_key: str
    title: str
    revision_no: int
    required: bool
    included: bool
    order: int | None
    reason: str


class PreviewDocumentOut(BaseModel):
    document_type: DocumentType
    label: str
    template_key: str
    template_revision_no: int
    clauses: list[ClauseDecisionOut]
    html: str


class PreviewOut(BaseModel):
    product_revision_no: int
    documents: list[PreviewDocumentOut]
    combined_html: str


class DocumentFileOut(ResponseModel):
    id: uuid.UUID
    file_name: str
    document_type: OutputDocumentType
    format: FileFormat
    page_no: int | None
    sha256: str
    size_bytes: int


class DocumentSetSummary(ResponseModel):
    id: uuid.UUID
    version_no: int
    status: DocumentSetStatus
    change_reason: str
    batch_id: uuid.UUID | None
    created_at: datetime
    published_at: datetime | None
    failure_reason: str | None


class DocumentSetDetail(DocumentSetSummary):
    product_id: uuid.UUID
    manifest: DocumentSetManifest
    files: list[DocumentFileOut]
