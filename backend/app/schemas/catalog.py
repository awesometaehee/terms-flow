"""조항·템플릿 요청·응답 모델. 실제 조항 문구는 승인된 원본만 입력한다."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models import ClauseKind, DocumentType, TemplateStatus
from app.schemas.common import Key, Name, NonBlankStr, RequestModel, ResponseModel
from app.schemas.kms import TagName


class ClauseCreate(RequestModel):
    """모듈 등록. 본문은 content(일반 텍스트, {{ 변수 }}) 또는 content_json(서식 본문) 중 하나."""

    clause_key: Key
    # 상품 문서 템플릿에서 쓸 문서 종류. KMS 모듈은 비워 둔다.
    document_type: DocumentType | None = None
    kind: ClauseKind = ClauseKind.COMMON
    title: Name
    category_id: uuid.UUID | None = None
    tags: list[TagName] = []
    content: NonBlankStr | None = None
    content_json: dict[str, Any] | None = None
    change_reason: NonBlankStr = "최초 등록"


class ClauseUpdate(RequestModel):
    """모듈 정보(제목·분류) 변경. 본문은 새 리비전으로만 바꾼다."""

    title: Name | None = None
    category_id: uuid.UUID | None = None
    clear_category: bool = False
    tags: list[TagName] | None = None


class ClauseRevisionCreate(RequestModel):
    # 편집을 시작할 때 본 최신 리비전 번호. 그 사이 다른 리비전이 생겼으면 409.
    base_revision_no: int
    content: NonBlankStr | None = None
    content_json: dict[str, Any] | None = None
    change_reason: NonBlankStr


class ClauseRevisionOut(BaseModel):
    id: uuid.UUID
    revision_no: int
    content: str
    content_json: dict[str, Any]
    change_reason: str
    created_at: datetime


class ClauseSummary(BaseModel):
    id: uuid.UUID
    clause_key: str
    document_type: DocumentType | None
    kind: ClauseKind
    title: str
    category_id: uuid.UUID | None
    tags: list[str]
    latest_revision_no: int
    excerpt: str
    updated_at: datetime
    # 삭제한 모듈 (이력에서만 보인다)
    deleted: bool = False


class ClauseDetail(ClauseSummary):
    revisions: list[ClauseRevisionOut]


class ClauseRuleIn(RequestModel):
    clause_key: Key
    # 포함 조건 (형식은 app/rendering/rules.py). 빈 객체는 항상 포함.
    condition: dict[str, Any] = Field(default_factory=dict)
    sort_order: int
    # True: 조건이 맞으면 반드시 포함. False: 조건이 맞아도 발행 시 사용자가 제외할 수 있다.
    required: bool = True


class TemplateCreate(RequestModel):
    template_key: Key
    document_type: DocumentType
    name: Name
    # 형식은 schemas/layout.v1.schema.json
    layout_definition: dict[str, Any]
    # 이 템플릿을 쓸 상품 조건. 같은 문서 종류에서 상품마다 정확히 1개 템플릿이 맞아야 한다.
    selection_condition: dict[str, Any] = Field(default_factory=dict)
    clause_rules: list[ClauseRuleIn] = []
    change_reason: NonBlankStr = "최초 등록"


class TemplateRevisionCreate(RequestModel):
    base_revision_no: int
    layout_definition: dict[str, Any]
    selection_condition: dict[str, Any] = Field(default_factory=dict)
    clause_rules: list[ClauseRuleIn] = []
    change_reason: NonBlankStr


class ClauseRuleOut(ResponseModel):
    clause_id: uuid.UUID
    clause_key: str
    condition: dict[str, Any]
    sort_order: int
    required: bool


class TemplateRevisionOut(ResponseModel):
    id: uuid.UUID
    revision_no: int
    layout_definition: dict[str, Any]
    selection_condition: dict[str, Any]
    clause_rules: list[ClauseRuleOut]
    change_reason: str
    created_at: datetime


class TemplateSummary(ResponseModel):
    id: uuid.UUID
    template_key: str
    document_type: DocumentType
    name: str
    status: TemplateStatus
    latest_revision_no: int


class TemplateDetail(TemplateSummary):
    revisions: list[TemplateRevisionOut]
