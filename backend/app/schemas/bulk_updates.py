import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import DocumentStatus, ProductStatus
from app.schemas.common import NonBlankStr, RequestModel

ItemResult = Literal["RUNNING", "SUCCEEDED", "FAILED", "SKIPPED"]
TargetType = Literal["PRODUCT", "DOCUMENT"]


class ImpactRequest(RequestModel):
    clause_id: uuid.UUID
    # 적용할 모듈 리비전. 현재 최신 리비전이어야 한다.
    revision_no: int


class BulkUpdateCreate(ImpactRequest):
    # 클라이언트가 만든 고유 ID. 네트워크 오류로 다시 보내도 작업이 중복 생성되지 않는다.
    request_id: str = Field(min_length=8, max_length=100)
    change_reason: NonBlankStr
    # 값이 비어 있는 문서에만 넣을 변수 값 (이미 값이 있는 문서는 그대로 둔다)
    variable_values: dict[str, str] = {}


class BulkUpdateRetry(RequestModel):
    variable_values: dict[str, str] = {}


class MissingVariable(BaseModel):
    """반영 후 값이 없어 발행할 수 없는 변수와, 그런 문서 수."""

    key: str
    label: str
    documents: int


class ClauseTextOut(BaseModel):
    revision_no: int
    content: str


class ImpactProduct(BaseModel):
    product_id: uuid.UUID
    product_code: str
    name: str
    status: ProductStatus
    current_version_no: int | None
    current_version_id: uuid.UUID | None
    # 현재 발행본에 들어간 이 모듈의 리비전 (없으면 아직 이 모듈로 발행된 적 없음)
    current_clause_revision_no: int | None
    reason: str | None = None


class ImpactDocument(BaseModel):
    document_id: uuid.UUID
    title: str
    status: DocumentStatus
    current_publication_no: int | None
    # 이 모듈을 쓰는 단락 중 원본 그대로이고 이전 리비전인 단락 수 (반영 대상)
    outdated_blocks: int = 0
    # 문서에서 고친 단락 수 (반영하지 않음)
    modified_blocks: int = 0
    # 변수 일괄 반영: 문서에 따로 입력한 값 (없으면 기본값을 씀)
    own_value: str | None = None
    reason: str | None = None


class ImpactOut(BaseModel):
    clause_id: uuid.UUID
    clause_key: str
    title: str
    revision: ClauseTextOut
    previous_revision: ClauseTextOut | None
    targets: list[ImpactProduct]
    excluded: list[ImpactProduct]
    document_targets: list[ImpactDocument]
    document_excluded: list[ImpactDocument]
    missing_variables: list[MissingVariable] = []


class BulkUpdateItemOut(BaseModel):
    target_type: TargetType
    target_id: uuid.UUID
    code: str | None
    name: str
    result: ItemResult
    message: str | None
    # 상품: 문서 세트 버전 ID, 문서: 발행본 ID
    version_id: uuid.UUID | None
    version_no: int | None


class BulkUpdateCounts(BaseModel):
    total: int
    running: int
    succeeded: int
    failed: int
    skipped: int


class BulkUpdateSummary(BaseModel):
    id: uuid.UUID
    request_id: str
    # MODULE: 공통 모듈 새 리비전 반영, VARIABLE: 변수 새 기본값 반영
    kind: Literal["MODULE", "VARIABLE"]
    clause_id: uuid.UUID | None
    clause_key: str | None
    clause_title: str | None
    revision_no: int | None
    variable_id: uuid.UUID | None
    variable_label: str | None
    variable_value: str | None
    change_reason: str
    created_at: datetime
    finished: bool
    counts: BulkUpdateCounts


class BulkUpdateDetail(BulkUpdateSummary):
    items: list[BulkUpdateItemOut]
    # 실행 시점에 제외된 상품·문서와 사유
    excluded: list[ImpactProduct]
    document_excluded: list[ImpactDocument]
    # 실패한 문서에서 값이 비어 있는 변수. 값을 넣어 다시 시도할 수 있다.
    missing_variables: list[MissingVariable] = []


class VariableImpactOut(BaseModel):
    """변수 기본값을 바꾼 뒤 다시 발행할 문서."""

    variable_id: uuid.UUID
    key: str
    label: str
    value: str | None
    # 기본값을 쓰는 사용 중 문서: 새 값으로 다시 발행한다.
    document_targets: list[ImpactDocument]
    # 문서에 값을 따로 입력한 사용 중 문서: 고른 문서만 기본값으로 바꾼다.
    own_value_documents: list[ImpactDocument]
    document_excluded: list[ImpactDocument]


class VariableBulkUpdateCreate(RequestModel):
    request_id: str = Field(min_length=8, max_length=100)
    # 문서에 입력한 값을 지우고 새 기본값을 쓰게 할 문서
    overwrite_document_ids: list[uuid.UUID] = []
