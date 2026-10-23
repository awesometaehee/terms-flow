import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.models import BundleType, ProductStatus, SalesChannel
from app.schemas.common import Code, Name, NonBlankStr, RequestModel, ResponseModel


class CompanyCreate(RequestModel):
    code: Code
    name: Name


class CompanyOut(ResponseModel):
    id: uuid.UUID
    code: str
    name: str


class VariantIn(RequestModel):
    variant_code: Code
    display_name: Name
    price_amount: int = Field(gt=0, description="원 단위 금액")
    sort_order: int
    # 형식은 schemas/composition.v{schemaVersion}.schema.json으로 검증한다.
    composition: dict[str, Any]


class ProductCreate(RequestModel):
    product_code: Code
    name: Name
    company_id: uuid.UUID
    channel: SalesChannel
    refund_type: Code
    bundle_type: BundleType
    variants: list[VariantIn] = Field(min_length=1)
    change_reason: NonBlankStr = "최초 등록"


class ProductUpdate(RequestModel):
    """보내지 않은 필드는 유지한다. variants를 보내면 판매 구성 전체를 그 목록으로 바꾼다."""

    lock_version: int
    change_reason: NonBlankStr
    name: Name | None = None
    company_id: uuid.UUID | None = None
    channel: SalesChannel | None = None
    refund_type: Code | None = None
    bundle_type: BundleType | None = None
    variants: list[VariantIn] | None = Field(default=None, min_length=1)


class StatusChange(RequestModel):
    status: ProductStatus
    lock_version: int
    reason: NonBlankStr


class VariantOut(ResponseModel):
    id: uuid.UUID
    variant_code: str
    display_name: str
    price_amount: int
    sort_order: int
    composition: dict[str, Any]


class ProductSummary(ResponseModel):
    id: uuid.UUID
    product_code: str
    name: str
    company: CompanyOut
    status: ProductStatus
    channel: SalesChannel
    refund_type: str
    bundle_type: BundleType
    lock_version: int
    variant_count: int
    latest_document_set_version_no: int | None
    updated_at: datetime


class ProductDetail(ProductSummary):
    variants: list[VariantOut]
    current_revision_no: int


class RevisionSummary(ResponseModel):
    revision_no: int
    change_reason: str
    created_at: datetime


class RevisionDetail(RevisionSummary):
    snapshot: dict[str, Any]


class StatusHistoryOut(ResponseModel):
    from_status: ProductStatus | None
    to_status: ProductStatus
    reason: str
    changed_at: datetime
