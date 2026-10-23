"""ORM 모델. 테이블 구성은 개발 가이드 6.2절을 따른다.

*_revisions, template_clause_rules, 발행된 document_set_versions·document_files는
DB 트리거로 수정·삭제를 막는다 (migrations/versions/0002 참고).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ProductStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class SalesChannel(enum.StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class BundleType(enum.StrEnum):
    STANDARD = "STANDARD"
    BUNDLE = "BUNDLE"


class DocumentType(enum.StrEnum):
    TERMS = "TERMS"
    TERMS_SUMMARY = "TERMS_SUMMARY"
    PRODUCT_DESCRIPTION = "PRODUCT_DESCRIPTION"


class OutputDocumentType(enum.StrEnum):
    """출력 파일 단위. 3종 문서와 통합본(COMBINED)."""

    TERMS = "TERMS"
    TERMS_SUMMARY = "TERMS_SUMMARY"
    PRODUCT_DESCRIPTION = "PRODUCT_DESCRIPTION"
    COMBINED = "COMBINED"


class ClauseKind(enum.StrEnum):
    COMMON = "COMMON"
    CONDITIONAL = "CONDITIONAL"


class TemplateStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DocumentSetStatus(enum.StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class BulkUpdateItemStatus(enum.StrEnum):
    """생성 시점의 결과. 렌더링 결과는 연결된 문서 세트 버전 상태로 판단한다."""

    QUEUED = "QUEUED"  # 문서 세트 버전을 만들고 렌더링 작업을 넣음
    SKIPPED = "SKIPPED"  # 실행 시 ACTIVE가 아니어서 건너뜀
    FAILED = "FAILED"  # 조합 실패 등으로 버전을 만들지 못함


class FileFormat(enum.StrEnum):
    PDF = "PDF"
    PNG = "PNG"


def _enum(enum_cls: type[enum.StrEnum], name: str) -> sa.Enum:
    """PostgreSQL ENUM 대신 VARCHAR + CHECK 제약으로 저장한다 (값 추가 마이그레이션이 쉽다)."""
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=30,
        values_callable=lambda e: [m.value for m in e],
    )


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(sa.String(50), unique=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    created_at: Mapped[datetime] = _created_at()


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = _uuid_pk()
    product_code: Mapped[str] = mapped_column(sa.String(50), unique=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("companies.id"))
    status: Mapped[ProductStatus] = mapped_column(
        _enum(ProductStatus, "status"), default=ProductStatus.DRAFT, index=True
    )
    channel: Mapped[SalesChannel] = mapped_column(_enum(SalesChannel, "channel"))
    refund_type: Mapped[str] = mapped_column(sa.String(50))
    bundle_type: Mapped[BundleType] = mapped_column(_enum(BundleType, "bundle_type"))
    lock_version: Mapped[int] = mapped_column(sa.Integer)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    company: Mapped[Company] = relationship(lazy="joined")
    variants: Mapped[list["ProductVariant"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="(ProductVariant.sort_order, ProductVariant.variant_code)",
    )

    # 낙관적 잠금: UPDATE마다 lock_version이 1씩 증가하고, 동시 수정은 StaleDataError가 된다.
    __mapper_args__ = {"version_id_col": lock_version}


class ProductStatusHistory(Base):
    __tablename__ = "product_status_history"

    id: Mapped[uuid.UUID] = _uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("products.id"), index=True)
    from_status: Mapped[ProductStatus | None] = mapped_column(_enum(ProductStatus, "from_status"))
    to_status: Mapped[ProductStatus] = mapped_column(_enum(ProductStatus, "to_status"))
    reason: Mapped[str] = mapped_column(sa.Text)
    changed_at: Mapped[datetime] = _created_at()


class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        sa.UniqueConstraint("product_id", "variant_code"),
        sa.CheckConstraint("price_amount > 0", name="price_amount_positive"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("products.id"))
    variant_code: Mapped[str] = mapped_column(sa.String(50))
    display_name: Mapped[str] = mapped_column(sa.String(200))
    price_amount: Mapped[int] = mapped_column(sa.BigInteger)
    composition: Mapped[dict[str, Any]] = mapped_column("composition_jsonb", JSONB)
    sort_order: Mapped[int] = mapped_column(sa.Integer)

    product: Mapped[Product] = relationship(back_populates="variants")


class ProductRevision(Base):
    __tablename__ = "product_revisions"
    __table_args__ = (sa.UniqueConstraint("product_id", "revision_no"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("products.id"))
    revision_no: Mapped[int] = mapped_column(sa.Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column("snapshot_jsonb", JSONB)
    change_reason: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created_at()


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = _uuid_pk()
    template_key: Mapped[str] = mapped_column(sa.String(100), unique=True)
    document_type: Mapped[DocumentType] = mapped_column(_enum(DocumentType, "document_type"))
    name: Mapped[str] = mapped_column(sa.String(200))
    status: Mapped[TemplateStatus] = mapped_column(
        _enum(TemplateStatus, "status"), default=TemplateStatus.ACTIVE
    )
    created_at: Mapped[datetime] = _created_at()

    revisions: Mapped[list["TemplateRevision"]] = relationship(
        order_by="TemplateRevision.revision_no"
    )


class TemplateRevision(Base):
    __tablename__ = "template_revisions"
    __table_args__ = (sa.UniqueConstraint("template_id", "revision_no"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    template_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("templates.id"))
    revision_no: Mapped[int] = mapped_column(sa.Integer)
    layout_definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # 이 템플릿을 쓸 상품 조건. 빈 객체는 모든 상품.
    # 예: 결합형 상품설명서는 {"bundle_type": ["BUNDLE"]}
    selection_condition: Mapped[dict[str, Any]] = mapped_column(
        "selection_condition_jsonb", JSONB, server_default=sa.text("'{}'::jsonb")
    )
    change_reason: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created_at()

    clause_rules: Mapped[list["TemplateClauseRule"]] = relationship(
        order_by="TemplateClauseRule.sort_order"
    )


class Clause(Base):
    """모듈(재사용 단락). KMS 문서와 상품 문서 템플릿이 함께 쓴다."""

    __tablename__ = "clauses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    clause_key: Mapped[str] = mapped_column(sa.String(100), unique=True)
    # 상품 문서 템플릿 전용 구분. KMS 모듈은 NULL (모든 문서에서 사용 가능)
    document_type: Mapped[DocumentType | None] = mapped_column(_enum(DocumentType, "document_type"))
    kind: Mapped[ClauseKind] = mapped_column(_enum(ClauseKind, "kind"))
    title: Mapped[str] = mapped_column(sa.String(200))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("categories.id"), index=True
    )
    created_at: Mapped[datetime] = _created_at()
    # 삭제한 모듈: 목록·검색·새 단락에서 빠진다. 이력이 참조하므로 행은 남긴다.
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    revisions: Mapped[list["ClauseRevision"]] = relationship(order_by="ClauseRevision.revision_no")
    tags: Mapped[list["Tag"]] = relationship(secondary="clause_tags", order_by="Tag.name")


class ClauseRevision(Base):
    __tablename__ = "clause_revisions"
    __table_args__ = (sa.UniqueConstraint("clause_id", "revision_no"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    clause_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("clauses.id"))
    revision_no: Mapped[int] = mapped_column(sa.Integer)
    # 일반 텍스트 (검색·기존 상품 문서용). 서식 본문이 있으면 그 텍스트 버전이다.
    content: Mapped[str] = mapped_column(sa.Text)
    # 서식 본문 (에디터 JSON). NULL이면 content를 문단으로 변환해 쓴다 (기존 조항).
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    change_reason: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created_at()

    @property
    def rich(self) -> dict[str, Any]:
        from app.richtext import from_plain

        return self.content_json if self.content_json is not None else from_plain(self.content)


class TemplateClauseRule(Base):
    __tablename__ = "template_clause_rules"
    __table_args__ = (sa.UniqueConstraint("template_revision_id", "clause_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    template_revision_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("template_revisions.id"))
    clause_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("clauses.id"))
    condition: Mapped[dict[str, Any]] = mapped_column("condition_jsonb", JSONB)
    sort_order: Mapped[int] = mapped_column(sa.Integer)
    required: Mapped[bool] = mapped_column(sa.Boolean)

    clause: Mapped[Clause] = relationship(lazy="joined")


class DocumentSetVersion(Base):
    __tablename__ = "document_set_versions"
    __table_args__ = (sa.UniqueConstraint("product_id", "version_no"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("products.id"))
    version_no: Mapped[int] = mapped_column(sa.Integer)
    product_revision_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("product_revisions.id"))
    manifest: Mapped[dict[str, Any]] = mapped_column("manifest_jsonb", JSONB)
    status: Mapped[DocumentSetStatus] = mapped_column(
        _enum(DocumentSetStatus, "status"), default=DocumentSetStatus.PENDING
    )
    change_reason: Mapped[str] = mapped_column(sa.Text)
    # 일괄 수정 작업(bulk_update_jobs, 4단계)과 연결한다.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("bulk_update_jobs.id"), index=True
    )
    created_at: Mapped[datetime] = _created_at()
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(sa.Text)

    files: Mapped[list["DocumentFile"]] = relationship(
        order_by="(DocumentFile.document_type, DocumentFile.format, DocumentFile.page_no)"
    )


class DocumentFile(Base):
    __tablename__ = "document_files"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_set_version_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("document_set_versions.id"), index=True
    )
    document_type: Mapped[OutputDocumentType] = mapped_column(
        _enum(OutputDocumentType, "document_type")
    )
    format: Mapped[FileFormat] = mapped_column(_enum(FileFormat, "format"))
    # PNG는 페이지별 파일이므로 페이지 번호를 가진다. PDF는 NULL.
    page_no: Mapped[int | None] = mapped_column(sa.Integer)
    storage_key: Mapped[str] = mapped_column(sa.String(500), unique=True)
    sha256: Mapped[str] = mapped_column(sa.String(64))
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    created_at: Mapped[datetime] = _created_at()


class BulkUpdateJob(Base):
    """일괄 반영 작업: 공통 모듈의 새 리비전 또는 변수의 새 기본값을 ACTIVE 대상에 적용한다."""

    __tablename__ = "bulk_update_jobs"
    __table_args__ = (
        sa.CheckConstraint(
            "(clause_id IS NULL) <> (variable_id IS NULL)"
            " AND (clause_id IS NULL) = (clause_revision_id IS NULL)",
            name="one_source",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    # 클라이언트가 만든 요청 ID. 같은 ID로 다시 요청하면 기존 작업을 돌려준다.
    request_id: Mapped[str] = mapped_column(sa.String(100), unique=True)
    clause_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("clauses.id"))
    clause_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("clause_revisions.id")
    )
    variable_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("variables.id"))
    # 반영한 변수 기본값 (작업 시점 값)
    variable_value: Mapped[str | None] = mapped_column(sa.Text)
    change_reason: Mapped[str] = mapped_column(sa.Text)
    # 실행 시점에 다시 확인한 대상·제외 상품과 상태
    target_snapshot: Mapped[dict[str, Any]] = mapped_column("target_snapshot_jsonb", JSONB)
    created_at: Mapped[datetime] = _created_at()

    clause: Mapped[Clause | None] = relationship(lazy="joined")
    clause_revision: Mapped[ClauseRevision | None] = relationship(lazy="joined")
    variable: Mapped["Variable | None"] = relationship(lazy="joined")
    items: Mapped[list["BulkUpdateItem"]] = relationship(order_by="BulkUpdateItem.created_at")


class BulkUpdateItem(Base):
    """일괄 수정 대상 하나. 상품(product_id) 또는 KMS 문서(document_id) 중 하나를 가리킨다."""

    __tablename__ = "bulk_update_items"
    __table_args__ = (
        sa.UniqueConstraint("job_id", "product_id"),
        sa.UniqueConstraint("job_id", "document_id"),
        sa.CheckConstraint("(product_id IS NULL) <> (document_id IS NULL)", name="one_target"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("bulk_update_jobs.id"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("products.id"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("documents.id"))
    status: Mapped[BulkUpdateItemStatus] = mapped_column(_enum(BulkUpdateItemStatus, "status"))
    document_set_version_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("document_set_versions.id")
    )
    publication_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("publications.id"))
    message: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    product: Mapped[Product | None] = relationship(lazy="joined")
    document_set_version: Mapped[DocumentSetVersion | None] = relationship(lazy="joined")
    document: Mapped["Document | None"] = relationship(lazy="joined")
    publication: Mapped["Publication | None"] = relationship(lazy="joined")


# --- KMS: 분류·변수·문서 -----------------------------------------------------------


class DocumentStatus(enum.StrEnum):
    DRAFT = "DRAFT"  # 작성 중
    ACTIVE = "ACTIVE"  # 사용 중 (공통 모듈 일괄 반영 대상)
    ENDED = "ENDED"  # 종료 (읽기 전용)


class BlockKind(enum.StrEnum):
    MODULE = "MODULE"  # 모듈을 가져온 단락 (기준 리비전 + 선택적 문서 내 수정본)
    TEXT = "TEXT"  # 이 문서에만 있는 단락


class VariableType(enum.StrEnum):
    TEXT = "TEXT"
    NUMBER = "NUMBER"
    DATE = "DATE"


class Category(Base):
    """모듈·문서 공용 카테고리 트리."""

    __tablename__ = "categories"
    __table_args__ = (sa.UniqueConstraint("parent_id", "name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(sa.String(100))
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime] = _created_at()


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(sa.String(50), unique=True)


clause_tags = sa.Table(
    "clause_tags",
    Base.metadata,
    sa.Column("clause_id", sa.ForeignKey("clauses.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("tag_id", sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)
document_tags = sa.Table(
    "document_tags",
    Base.metadata,
    sa.Column("document_id", sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("tag_id", sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Variable(Base):
    """본문에 [이름] 칩으로 들어가는 변수. 값은 문서마다 입력한다."""

    __tablename__ = "variables"

    id: Mapped[uuid.UUID] = _uuid_pk()
    key: Mapped[str] = mapped_column(sa.String(100), unique=True)
    label: Mapped[str] = mapped_column(sa.String(100))
    value_type: Mapped[VariableType] = mapped_column(_enum(VariableType, "value_type"))
    default_value: Mapped[str | None] = mapped_column(sa.Text)
    description: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created_at()
    # 삭제한 변수: 목록·새 본문에서 빠진다. 이전 본문·발행본의 이름 표시를 위해 행은 남긴다.
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Document(Base):
    """KMS 문서. 모듈과 직접 쓴 단락을 순서대로 조합한다 (현재 작업 상태)."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str] = mapped_column(sa.String(200))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("categories.id"), index=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        _enum(DocumentStatus, "status"), default=DocumentStatus.DRAFT, index=True
    )
    variable_values: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    # 검색용 본문 텍스트 (저장 시 갱신)
    search_text: Mapped[str] = mapped_column(sa.Text, default="")
    lock_version: Mapped[int] = mapped_column(sa.Integer)
    created_at: Mapped[datetime] = _created_at()
    # 삭제한 문서: 목록·검색·일괄 반영에서 빠진다. 리비전·발행본이 참조하므로 행은 남긴다.
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    blocks: Mapped[list["DocumentBlock"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentBlock.position"
    )
    tags: Mapped[list[Tag]] = relationship(secondary="document_tags", order_by="Tag.name")

    __mapper_args__ = {"version_id_col": lock_version}


class DocumentBlock(Base):
    __tablename__ = "document_blocks"
    __table_args__ = (
        sa.CheckConstraint(
            "(kind = 'MODULE' AND clause_id IS NOT NULL AND clause_revision_id IS NOT NULL)"
            " OR (kind = 'TEXT' AND clause_id IS NULL AND content_json IS NOT NULL)",
            name="kind_fields",
        ),
    )

    # 클라이언트가 만든 ID를 그대로 써서 다시 저장해도 단락 ID가 유지된다.
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(sa.Integer)
    kind: Mapped[BlockKind] = mapped_column(_enum(BlockKind, "kind"))
    clause_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("clauses.id"), index=True)
    # 이 단락이 기준으로 삼는 모듈 리비전
    clause_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("clause_revisions.id")
    )
    # MODULE: 문서 안에서 고친 본문 (NULL이면 원본 그대로), TEXT: 단락 본문
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    document: Mapped[Document] = relationship(back_populates="blocks")
    clause: Mapped[Clause | None] = relationship(lazy="joined")
    clause_revision: Mapped[ClauseRevision | None] = relationship(lazy="joined")


class DocumentRevision(Base):
    """문서 저장 시점의 불변 스냅샷. 단락의 실제 본문까지 담아 그대로 재현할 수 있다."""

    __tablename__ = "document_revisions"
    __table_args__ = (sa.UniqueConstraint("document_id", "revision_no"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("documents.id"), index=True)
    revision_no: Mapped[int] = mapped_column(sa.Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column("snapshot_jsonb", JSONB)
    change_reason: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created_at()


class Publication(Base):
    """문서 리비전을 PDF·PNG로 출력한 발행본."""

    __tablename__ = "publications"
    __table_args__ = (sa.UniqueConstraint("document_id", "version_no"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("documents.id"), index=True)
    version_no: Mapped[int] = mapped_column(sa.Integer)
    document_revision_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("document_revisions.id"))
    status: Mapped[DocumentSetStatus] = mapped_column(
        _enum(DocumentSetStatus, "status"), default=DocumentSetStatus.PENDING
    )
    change_reason: Mapped[str] = mapped_column(sa.Text)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("bulk_update_jobs.id"), index=True
    )
    renderer_version: Mapped[str | None] = mapped_column(sa.Text)
    failure_reason: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = _created_at()
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    revision: Mapped[DocumentRevision] = relationship(lazy="joined")
    files: Mapped[list["PublicationFile"]] = relationship(
        order_by="(PublicationFile.format, PublicationFile.page_no)"
    )


class PublicationFile(Base):
    __tablename__ = "publication_files"

    id: Mapped[uuid.UUID] = _uuid_pk()
    publication_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("publications.id"), index=True)
    format: Mapped[FileFormat] = mapped_column(_enum(FileFormat, "format"))
    page_no: Mapped[int | None] = mapped_column(sa.Integer)
    storage_key: Mapped[str] = mapped_column(sa.String(500), unique=True)
    sha256: Mapped[str] = mapped_column(sa.String(64))
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    created_at: Mapped[datetime] = _created_at()
