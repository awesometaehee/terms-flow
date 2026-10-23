"""KMS 요청·응답 모델: 카테고리·태그·변수·문서·발행본·검색."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.models import BlockKind, DocumentSetStatus, DocumentStatus, FileFormat, VariableType
from app.schemas.common import Key, Name, NonBlankStr, RequestModel, ResponseModel

TagName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]

# --- 카테고리·태그 -----------------------------------------------------------------


class CategoryCreate(RequestModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    parent_id: uuid.UUID | None = None
    sort_order: int = 0


class CategoryUpdate(RequestModel):
    name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
        | None
    ) = None
    parent_id: uuid.UUID | None = None
    # parent_id를 비우려면(최상위로 이동) move_to_root=true
    move_to_root: bool = False
    sort_order: int | None = None


class CategoryOut(ResponseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    sort_order: int


class TagOut(BaseModel):
    name: str
    module_count: int
    document_count: int


# --- 변수 --------------------------------------------------------------------------


class VariableCreate(RequestModel):
    key: Key
    label: Name
    value_type: VariableType = VariableType.TEXT
    default_value: str | None = None
    description: str | None = None


class VariableUpdate(RequestModel):
    label: Name | None = None
    value_type: VariableType | None = None
    default_value: str | None = None
    description: str | None = None


class VariableOut(ResponseModel):
    id: uuid.UUID
    key: str
    label: str
    value_type: VariableType
    default_value: str | None
    description: str | None


# --- 문서 --------------------------------------------------------------------------


class DocumentCreate(RequestModel):
    title: Name
    category_id: uuid.UUID | None = None
    tags: list[TagName] = []
    # 다른 문서의 현재 단락·변수 값을 복사해 시작한다.
    copy_from_document_id: uuid.UUID | None = None


class BlockIn(RequestModel):
    # 클라이언트가 만든 단락 ID (같은 단락을 다시 저장할 때 유지된다)
    id: uuid.UUID
    kind: BlockKind
    # MODULE: 모듈과 기준 리비전 번호, content_json은 문서에서 고친 본문(원본과 같으면 무시)
    clause_id: uuid.UUID | None = None
    clause_revision_no: int | None = None
    content_json: dict[str, Any] | None = None


class DocumentSave(RequestModel):
    lock_version: int
    change_reason: NonBlankStr = "저장"
    title: Name
    category_id: uuid.UUID | None = None
    tags: list[TagName] = []
    variable_values: dict[str, str] = {}
    blocks: list[BlockIn]


class DocumentStatusChange(RequestModel):
    status: DocumentStatus
    lock_version: int
    reason: NonBlankStr


class PromoteBlock(RequestModel):
    """문서에서 고친 모듈 단락을 원본 모듈의 새 리비전으로 저장한다."""

    lock_version: int
    change_reason: NonBlankStr


class BlockOut(BaseModel):
    id: uuid.UUID
    kind: BlockKind
    clause_id: uuid.UUID | None
    clause_key: str | None
    clause_title: str | None
    clause_revision_no: int | None
    latest_revision_no: int | None
    # 화면에 보일 본문 (문서 수정본이 있으면 그것, 없으면 모듈 리비전 본문)
    content_json: dict[str, Any]
    # 원본 모듈 리비전 본문 (수정본과 비교·되돌리기용). TEXT 단락은 None
    original_content_json: dict[str, Any] | None
    modified: bool
    outdated: bool


class DocumentSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: DocumentStatus
    category_id: uuid.UUID | None
    tags: list[str]
    block_count: int
    revision_no: int
    latest_publication_no: int | None
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    lock_version: int
    variable_values: dict[str, str]
    variables: list[VariableOut]
    blocks: list[BlockOut]


class DocumentRevisionSummary(ResponseModel):
    revision_no: int
    change_reason: str
    created_at: datetime


class DocumentRevisionDetail(DocumentRevisionSummary):
    snapshot: dict[str, Any]


# --- 발행본 ------------------------------------------------------------------------


class PublishDocument(RequestModel):
    change_reason: NonBlankStr


class PublicationFileOut(BaseModel):
    id: uuid.UUID
    file_name: str
    format: FileFormat
    page_no: int | None
    sha256: str
    size_bytes: int


class PublicationSummary(ResponseModel):
    id: uuid.UUID
    version_no: int
    status: DocumentSetStatus
    change_reason: str
    batch_id: uuid.UUID | None
    revision_no: int
    renderer_version: str | None
    failure_reason: str | None
    created_at: datetime
    published_at: datetime | None


class PublicationDetail(PublicationSummary):
    document_id: uuid.UUID
    files: list[PublicationFileOut]


# --- 검색 --------------------------------------------------------------------------


class SearchHit(BaseModel):
    kind: Literal["MODULE", "DOCUMENT"]
    id: uuid.UUID
    title: str
    subtitle: str
    excerpt: str
    tags: list[str]
    category_id: uuid.UUID | None


class SearchOut(BaseModel):
    query: str
    hits: list[SearchHit] = Field(default_factory=list)
