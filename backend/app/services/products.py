"""상품·판매 구성·상품 버전.

- 상품 데이터가 바뀔 때마다 불변 스냅샷(product_revisions)을 새로 남긴다.
- ENDED 상품은 수정·상태 변경·새 발행을 거부한다 (DB 트리거로도 막는다).
- 수정 요청은 lock_version이 현재 값과 같아야 한다 (낙관적 잠금).
"""

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, selectinload

from app.composition import validate_composition
from app.db import like_pattern
from app.errors import ConflictError, FieldError, NotFoundError, ValidationFailed, join_path
from app.models import (
    Company,
    DocumentSetStatus,
    DocumentSetVersion,
    Product,
    ProductRevision,
    ProductStatus,
    ProductStatusHistory,
    ProductVariant,
)
from app.schemas.products import (
    CompanyCreate,
    ProductCreate,
    ProductDetail,
    ProductSummary,
    ProductUpdate,
    StatusChange,
    VariantIn,
    VariantOut,
)

SNAPSHOT_SCHEMA_VERSION = 1

# 재판매 등 ENDED 이후 전환 정책은 미확정이므로 허용하지 않는다 (가이드 14장 3번).
ALLOWED_TRANSITIONS: dict[ProductStatus, set[ProductStatus]] = {
    ProductStatus.DRAFT: {ProductStatus.ACTIVE},
    ProductStatus.ACTIVE: {ProductStatus.ENDED},
    ProductStatus.ENDED: set(),
}


# --- 법인 ---------------------------------------------------------------------


def create_company(session: Session, data: CompanyCreate) -> Company:
    if session.scalar(sa.select(Company.id).where(Company.code == data.code)):
        raise ConflictError("이미 존재하는 법인 코드입니다.", code="DUPLICATE_COMPANY_CODE")
    company = Company(code=data.code, name=data.name)
    session.add(company)
    session.flush()
    return company


def list_companies(session: Session) -> Sequence[Company]:
    return session.scalars(sa.select(Company).order_by(Company.code)).all()


# --- 검증 ---------------------------------------------------------------------


def validate_variants(variants: Sequence[VariantIn], prefix: str = "variants") -> None:
    errors: list[FieldError] = []
    seen_codes: set[str] = set()
    for i, variant in enumerate(variants):
        if variant.variant_code in seen_codes:
            errors.append(
                FieldError(
                    path=f"{prefix}[{i}].variant_code", message="판매 구성 코드가 중복됩니다."
                )
            )
        seen_codes.add(variant.variant_code)
        for err in validate_composition(variant.composition):
            path = join_path(f"{prefix}[{i}].composition", err.path)
            errors.append(FieldError(path=path, message=err.message))
    if errors:
        raise ValidationFailed(errors)


def _require_company(session: Session, company_id: uuid.UUID) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise ValidationFailed([FieldError(path="company_id", message="존재하지 않는 법인입니다.")])
    return company


def ensure_not_ended(product: Product) -> None:
    if product.status == ProductStatus.ENDED:
        raise ConflictError(
            "판매 종료(ENDED) 상품은 수정하거나 새로 발행할 수 없습니다.", code="PRODUCT_ENDED"
        )


def _check_lock_version(product: Product, lock_version: int) -> None:
    if product.lock_version != lock_version:
        raise ConflictError(
            "다른 사용자가 먼저 수정했습니다. 최신 내용을 다시 조회하세요.",
            code="VERSION_CONFLICT",
        )


# --- 조회 ---------------------------------------------------------------------


def get_product(session: Session, product_id: uuid.UUID, *, for_update: bool = False) -> Product:
    stmt = sa.select(Product).where(Product.id == product_id)
    if for_update:
        # 상품 행을 잠가 리비전·문서 버전 번호가 동시에 같은 값으로 생기지 않게 한다.
        stmt = stmt.with_for_update(of=Product)
    product = session.scalar(stmt.options(selectinload(Product.variants)))
    if product is None:
        raise NotFoundError("상품을 찾을 수 없습니다.")
    return product


def _latest_revision_no(session: Session, product_id: uuid.UUID) -> int:
    stmt = sa.select(sa.func.max(ProductRevision.revision_no)).where(
        ProductRevision.product_id == product_id
    )
    return session.scalar(stmt) or 0


def latest_revision(session: Session, product_id: uuid.UUID) -> ProductRevision:
    revision = session.scalar(
        sa.select(ProductRevision)
        .where(ProductRevision.product_id == product_id)
        .order_by(ProductRevision.revision_no.desc())
        .limit(1)
    )
    if revision is None:  # 상품 생성 시 1번 리비전을 만들므로 정상적으로는 발생하지 않는다.
        raise NotFoundError("상품 버전이 없습니다.")
    return revision


def _latest_published_versions(
    session: Session, product_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not product_ids:
        return {}
    rows = session.execute(
        sa.select(DocumentSetVersion.product_id, sa.func.max(DocumentSetVersion.version_no))
        .where(
            DocumentSetVersion.product_id.in_(product_ids),
            DocumentSetVersion.status == DocumentSetStatus.PUBLISHED,
        )
        .group_by(DocumentSetVersion.product_id)
    ).all()
    return {product_id: version_no for product_id, version_no in rows}


def _summary_fields(product: Product, latest_published: int | None) -> dict[str, Any]:
    return {
        "id": product.id,
        "product_code": product.product_code,
        "name": product.name,
        "company": product.company,
        "status": product.status,
        "channel": product.channel,
        "refund_type": product.refund_type,
        "bundle_type": product.bundle_type,
        "lock_version": product.lock_version,
        "variant_count": len(product.variants),
        "latest_document_set_version_no": latest_published,
        "updated_at": product.updated_at,
    }


def to_detail(session: Session, product: Product) -> ProductDetail:
    latest = _latest_published_versions(session, [product.id]).get(product.id)
    return ProductDetail(
        **_summary_fields(product, latest),
        variants=[VariantOut.model_validate(v) for v in _sorted_variants(product)],
        current_revision_no=_latest_revision_no(session, product.id),
    )


def list_products(
    session: Session,
    *,
    status: ProductStatus | None = None,
    company_id: uuid.UUID | None = None,
    q: str | None = None,
) -> list[ProductSummary]:
    stmt = sa.select(Product).options(selectinload(Product.variants)).order_by(Product.name)
    if status is not None:
        stmt = stmt.where(Product.status == status)
    if company_id is not None:
        stmt = stmt.where(Product.company_id == company_id)
    if q:
        pattern = like_pattern(q)
        stmt = stmt.where(sa.or_(Product.name.ilike(pattern), Product.product_code.ilike(pattern)))
    products = session.scalars(stmt).all()
    latest = _latest_published_versions(session, [p.id for p in products])
    return [ProductSummary(**_summary_fields(p, latest.get(p.id))) for p in products]


def list_revisions(session: Session, product_id: uuid.UUID) -> Sequence[ProductRevision]:
    get_product(session, product_id)
    return session.scalars(
        sa.select(ProductRevision)
        .where(ProductRevision.product_id == product_id)
        .order_by(ProductRevision.revision_no)
    ).all()


def get_revision(session: Session, product_id: uuid.UUID, revision_no: int) -> ProductRevision:
    revision = session.scalar(
        sa.select(ProductRevision).where(
            ProductRevision.product_id == product_id, ProductRevision.revision_no == revision_no
        )
    )
    if revision is None:
        raise NotFoundError("상품 버전을 찾을 수 없습니다.")
    return revision


def list_status_history(session: Session, product_id: uuid.UUID) -> Sequence[ProductStatusHistory]:
    get_product(session, product_id)
    return session.scalars(
        sa.select(ProductStatusHistory)
        .where(ProductStatusHistory.product_id == product_id)
        .order_by(ProductStatusHistory.changed_at, ProductStatusHistory.id)
    ).all()


# --- 스냅샷 -------------------------------------------------------------------


def _sorted_variants(product: Product) -> list[ProductVariant]:
    return sorted(product.variants, key=lambda v: (v.sort_order, v.variant_code))


def build_snapshot(product: Product) -> dict[str, Any]:
    """문서 생성에 쓰이는 상품 입력 전체. 법인명도 함께 고정한다."""
    return {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "product": {
            "id": str(product.id),
            "product_code": product.product_code,
            "name": product.name,
            "company": {
                "id": str(product.company.id),
                "code": product.company.code,
                "name": product.company.name,
            },
            "channel": product.channel.value,
            "refund_type": product.refund_type,
            "bundle_type": product.bundle_type.value,
        },
        "variants": [
            {
                "variant_code": v.variant_code,
                "display_name": v.display_name,
                "price_amount": v.price_amount,
                "sort_order": v.sort_order,
                "composition": v.composition,
            }
            for v in _sorted_variants(product)
        ],
    }


def _add_revision(session: Session, product: Product, change_reason: str) -> ProductRevision:
    session.flush()
    session.refresh(product, ["company"])
    revision = ProductRevision(
        product_id=product.id,
        revision_no=_latest_revision_no(session, product.id) + 1,
        snapshot=build_snapshot(product),
        change_reason=change_reason,
    )
    session.add(revision)
    session.flush()
    return revision


# --- 변경 ---------------------------------------------------------------------


def _new_variant(data: VariantIn) -> ProductVariant:
    return ProductVariant(
        variant_code=data.variant_code,
        display_name=data.display_name,
        price_amount=data.price_amount,
        sort_order=data.sort_order,
        composition=data.composition,
    )


def create_product(session: Session, data: ProductCreate) -> Product:
    validate_variants(data.variants)
    _require_company(session, data.company_id)
    if session.scalar(sa.select(Product.id).where(Product.product_code == data.product_code)):
        raise ConflictError("이미 존재하는 상품 코드입니다.", code="DUPLICATE_PRODUCT_CODE")

    product = Product(
        product_code=data.product_code,
        name=data.name,
        company_id=data.company_id,
        status=ProductStatus.DRAFT,
        channel=data.channel,
        refund_type=data.refund_type,
        bundle_type=data.bundle_type,
        variants=[_new_variant(v) for v in data.variants],
    )
    session.add(product)
    session.flush()
    session.add(
        ProductStatusHistory(
            product_id=product.id, from_status=None, to_status=ProductStatus.DRAFT, reason="등록"
        )
    )
    _add_revision(session, product, data.change_reason)
    return product


def _replace_variants(product: Product, variants: Sequence[VariantIn]) -> None:
    """variant_code가 같으면 기존 행을 고치고, 없어진 코드는 삭제, 새 코드는 추가한다."""
    existing = {v.variant_code: v for v in product.variants}
    keep: list[ProductVariant] = []
    for data in variants:
        row = existing.get(data.variant_code)
        if row is None:
            keep.append(_new_variant(data))
            continue
        row.display_name = data.display_name
        row.price_amount = data.price_amount
        row.sort_order = data.sort_order
        row.composition = data.composition
        keep.append(row)
    product.variants = keep


def update_product(session: Session, product_id: uuid.UUID, data: ProductUpdate) -> Product:
    product = get_product(session, product_id, for_update=True)
    ensure_not_ended(product)
    _check_lock_version(product, data.lock_version)
    if data.variants is not None:
        validate_variants(data.variants)
    if data.company_id is not None:
        _require_company(session, data.company_id)
        product.company_id = data.company_id

    for field in ("name", "channel", "refund_type", "bundle_type"):
        value = getattr(data, field)
        if value is not None:
            setattr(product, field, value)
    if data.variants is not None:
        _replace_variants(product, data.variants)
    # 판매 구성만 바뀌어도 상품 행을 UPDATE해 lock_version을 올린다.
    product.updated_at = sa.func.now()

    _add_revision(session, product, data.change_reason)
    return product


def change_status(session: Session, product_id: uuid.UUID, data: StatusChange) -> Product:
    product = get_product(session, product_id, for_update=True)
    if data.status not in ALLOWED_TRANSITIONS[product.status]:
        if product.status == ProductStatus.ENDED:
            ensure_not_ended(product)
        raise ConflictError(
            f"{product.status.value}에서 {data.status.value}(으)로 바꿀 수 없습니다.",
            code="INVALID_STATUS_TRANSITION",
        )
    _check_lock_version(product, data.lock_version)
    session.add(
        ProductStatusHistory(
            product_id=product.id,
            from_status=product.status,
            to_status=data.status,
            reason=data.reason,
        )
    )
    product.status = data.status
    session.flush()
    return product
