"""공통 모듈·변수 일괄 수정 (가이드 7장, KMS 문서 포함).

변수: 기본값을 바꾼 뒤, 그 변수를 쓰는 사용 중 문서를 새 값으로 다시 발행한다. 문서에 값을
따로 입력한 문서는 사용자가 고른 것만 입력값을 지우고 기본값을 쓰게 한다.

1. 영향 분석: 모듈의 새 리비전이 들어갈 상품·문서를 찾는다. 대상은 ACTIVE(판매 중·사용 중)뿐이다.
   - 상품: ENDED(판매 종료)·DRAFT(판매 전)·이미 반영됨은 사유와 함께 제외
   - 문서: 종료·작성 중·문서에서 고친 단락만 있음·이미 반영됨은 사유와 함께 제외
2. 실행: 영향 분석을 다시 수행해 대상·상태를 target_snapshot에 고정하고, 대상마다 별도
   세이브포인트에서 상태를 재확인한 뒤 새 버전(상품: 문서 세트 버전, 문서: 리비전+발행본)을 만든다.
   렌더링은 worker가 한다.
3. 재시도: 실패한 대상만 다시 처리한다. 렌더링 실패는 같은 버전을 다시 렌더링하므로
   버전 번호가 늘지 않는다.
종료된 상품·문서의 데이터·버전·파일은 이 흐름에서 절대 수정하지 않는다 (DB 트리거로도 막는다).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import Session, selectinload

from app import richtext
from app.errors import AppError, ConflictError, NotFoundError
from app.models import (
    BulkUpdateItem,
    BulkUpdateItemStatus,
    BulkUpdateJob,
    Clause,
    ClauseRevision,
    Document,
    DocumentBlock,
    DocumentSetStatus,
    DocumentSetVersion,
    DocumentStatus,
    Product,
    ProductStatus,
    Publication,
    Variable,
)
from app.rendering.composer import CompositionFailed
from app.rendering.kms import missing_variables
from app.rendering.loader import plan_latest
from app.schemas.bulk_updates import (
    BulkUpdateCounts,
    BulkUpdateCreate,
    BulkUpdateDetail,
    BulkUpdateItemOut,
    BulkUpdateRetry,
    BulkUpdateSummary,
    ClauseTextOut,
    ImpactDocument,
    ImpactOut,
    ImpactProduct,
    ItemResult,
    MissingVariable,
    VariableBulkUpdateCreate,
    VariableImpactOut,
)
from app.schemas.document_sets import DocumentSetManifest
from app.services import documents as document_service
from app.services import publications as publication_service
from app.services.document_sets import (
    latest_published,
    request_publication,
    retry_failed_version,
    user_excluded_keys,
)
from app.services.products import get_product, latest_revision
from app.services.taxonomy import variable_labels, variables_by_key

ENDED_REASON = "판매 종료(ENDED) 상품은 변경하지 않습니다."
DRAFT_REASON = "판매 전(DRAFT) 상품입니다. 발행 시 최신 모듈이 자동으로 적용됩니다."
UP_TO_DATE_REASON = "현재 발행본에 이미 이 리비전이 반영되어 있습니다."
DOC_ENDED_REASON = "종료된 문서는 변경하지 않습니다."
DOC_DRAFT_REASON = "작성 중인 문서입니다. 편집 화면의 '새 버전 있음'에서 직접 반영하세요."
DOC_MODIFIED_REASON = "문서에서 고친 단락이라 원본 변경을 반영하지 않습니다."
DOC_UP_TO_DATE_REASON = "이미 이 리비전을 쓰고 있습니다."
VAR_DRAFT_REASON = "작성 중인 문서입니다. 다음에 저장할 때 새 값이 들어갑니다."
VAR_UP_TO_DATE_REASON = "이미 이 값으로 저장되어 있습니다."


@dataclass
class _Impact:
    clause: Clause
    revision: ClauseRevision
    previous: ClauseRevision | None
    targets: list[ImpactProduct]
    excluded: list[ImpactProduct]
    document_targets: list[ImpactDocument]
    document_excluded: list[ImpactDocument]
    missing_variables: list[MissingVariable]


@dataclass
class RenderQueue:
    """작업 큐에 넣을 렌더링 대상."""

    versions: list[uuid.UUID] = field(default_factory=list)
    publications: list[uuid.UUID] = field(default_factory=list)


# --- 영향 분석 ---------------------------------------------------------------------


def _clause_revision_in(version: DocumentSetVersion | None, clause_key: str) -> int | None:
    if version is None:
        return None
    manifest = DocumentSetManifest.model_validate(version.manifest)
    for doc in manifest.documents:
        for c in doc.clauses:
            if c.clause_key == clause_key:
                return c.revision_no
    return None


def _impact_row(
    product: Product,
    published: DocumentSetVersion | None,
    current_rev: int | None,
    reason: str | None,
) -> ImpactProduct:
    return ImpactProduct(
        product_id=product.id,
        product_code=product.product_code,
        name=product.name,
        status=product.status,
        current_version_no=published.version_no if published else None,
        current_version_id=published.id if published else None,
        current_clause_revision_no=current_rev,
        reason=reason,
    )


def _analyze_products(
    session: Session, clause: Clause, revision_no: int
) -> tuple[list[ImpactProduct], list[ImpactProduct]]:
    targets: list[ImpactProduct] = []
    excluded: list[ImpactProduct] = []
    products = session.scalars(sa.select(Product).order_by(Product.product_code)).all()
    for product in products:
        published = latest_published(session, product.id)
        current_rev = _clause_revision_in(published, clause.clause_key)

        if product.status == ProductStatus.ENDED:
            if current_rev is not None:
                excluded.append(_impact_row(product, published, current_rev, ENDED_REASON))
            continue
        snapshot = latest_revision(session, product.id).snapshot
        try:
            plan = plan_latest(session, snapshot, user_excluded_keys(published))
        except CompositionFailed as exc:
            if current_rev is not None:
                reason = "문서를 조합할 수 없습니다: " + str(exc)
                excluded.append(_impact_row(product, published, current_rev, reason))
            continue
        uses_clause = any(
            c.clause_key == clause.clause_key for d in plan.documents for c in d.included
        )
        if not uses_clause:
            continue
        if product.status == ProductStatus.DRAFT:
            excluded.append(_impact_row(product, published, current_rev, DRAFT_REASON))
        elif current_rev == revision_no:
            excluded.append(_impact_row(product, published, current_rev, UP_TO_DATE_REASON))
        else:
            targets.append(_impact_row(product, published, current_rev, None))
    return targets, excluded


def _document_row(
    document: Document,
    publication_no: int | None,
    outdated: int,
    modified: int,
    reason: str | None,
) -> ImpactDocument:
    return ImpactDocument(
        document_id=document.id,
        title=document.title,
        status=document.status,
        current_publication_no=publication_no,
        outdated_blocks=outdated,
        modified_blocks=modified,
        reason=reason,
    )


def _used_keys_after(
    document: Document, clause_id: uuid.UUID, revision: ClauseRevision
) -> list[str]:
    """새 리비전을 반영한 뒤 문서 본문에 쓰일 변수 키."""
    keys: dict[str, None] = {}
    for block in document.blocks:
        if block.clause_id == clause_id and block.content_json is None:
            content = revision.rich
        else:
            content = document_service.effective_content(block)
        keys.update(dict.fromkeys(richtext.variable_keys(content)))
    return list(keys)


def _count_missing(session: Session, missing: dict[str, int]) -> list[MissingVariable]:
    labels = variable_labels(session)
    return [MissingVariable(key=k, label=labels.get(k, k), documents=n) for k, n in missing.items()]


def _missing_in_targets(
    session: Session, clause: Clause, revision: ClauseRevision, targets: list[ImpactDocument]
) -> list[MissingVariable]:
    """반영 후 값이 비어 발행할 수 없게 되는 변수 (기본값도 문서 값도 없음)."""
    if not targets:
        return []
    defaults = {k for k, v in variables_by_key(session).items() if v.default_value}
    documents = session.scalars(
        sa.select(Document)
        .where(Document.id.in_([t.document_id for t in targets]))
        .options(selectinload(Document.blocks))
    ).all()
    missing: dict[str, int] = {}
    for document in documents:
        valued = defaults | {k for k, v in document.variable_values.items() if v}
        for key in _used_keys_after(document, clause.id, revision):
            if key not in valued:
                missing[key] = missing.get(key, 0) + 1
    return _count_missing(session, missing)


def _analyze_documents(
    session: Session, clause: Clause, revision: ClauseRevision
) -> tuple[list[ImpactDocument], list[ImpactDocument]]:
    documents = session.scalars(
        sa.select(Document)
        .where(
            Document.deleted_at.is_(None),
            Document.blocks.any(DocumentBlock.clause_id == clause.id),
        )
        .options(selectinload(Document.blocks))
        .order_by(Document.title)
    ).all()
    publications = (
        dict(
            session.execute(
                sa.select(Publication.document_id, sa.func.max(Publication.version_no))
                .where(
                    Publication.document_id.in_([d.id for d in documents]),
                    Publication.status == DocumentSetStatus.PUBLISHED,
                )
                .group_by(Publication.document_id)
            ).all()
        )
        if documents
        else {}
    )
    targets: list[ImpactDocument] = []
    excluded: list[ImpactDocument] = []
    for document in documents:
        blocks = [b for b in document.blocks if b.clause_id == clause.id]
        outdated = [
            b for b in blocks if b.content_json is None and b.clause_revision_id != revision.id
        ]
        modified = [b for b in blocks if b.content_json is not None]

        reason: str | None = None
        if document.status == DocumentStatus.ENDED:
            reason = DOC_ENDED_REASON
        elif not outdated:
            reason = DOC_MODIFIED_REASON if modified else DOC_UP_TO_DATE_REASON
        elif document.status == DocumentStatus.DRAFT:
            reason = DOC_DRAFT_REASON
        row = _document_row(
            document, publications.get(document.id), len(outdated), len(modified), reason
        )
        (excluded if reason else targets).append(row)
    return targets, excluded


def _analyze(session: Session, clause_id: uuid.UUID, revision_no: int) -> _Impact:
    clause = session.scalar(
        sa.select(Clause).where(Clause.id == clause_id).options(selectinload(Clause.revisions))
    )
    if clause is None:
        raise NotFoundError("모듈을 찾을 수 없습니다.")
    by_no = {r.revision_no: r for r in clause.revisions}
    if revision_no not in by_no:
        raise NotFoundError("모듈 리비전을 찾을 수 없습니다.")
    latest_no = clause.revisions[-1].revision_no
    if revision_no != latest_no:
        raise ConflictError(
            f"최신 리비전({latest_no}번)만 적용할 수 있습니다. 다시 영향 분석을 하세요.",
            code="VERSION_CONFLICT",
        )
    targets, excluded = _analyze_products(session, clause, revision_no)
    document_targets, document_excluded = _analyze_documents(session, clause, by_no[revision_no])
    return _Impact(
        clause=clause,
        revision=by_no[revision_no],
        previous=by_no.get(revision_no - 1),
        targets=targets,
        excluded=excluded,
        document_targets=document_targets,
        document_excluded=document_excluded,
        missing_variables=_missing_in_targets(
            session, clause, by_no[revision_no], document_targets
        ),
    )


def analyze_impact(session: Session, clause_id: uuid.UUID, revision_no: int) -> ImpactOut:
    impact = _analyze(session, clause_id, revision_no)
    return ImpactOut(
        clause_id=impact.clause.id,
        clause_key=impact.clause.clause_key,
        title=impact.clause.title,
        revision=ClauseTextOut(
            revision_no=impact.revision.revision_no, content=impact.revision.content
        ),
        previous_revision=(
            ClauseTextOut(revision_no=impact.previous.revision_no, content=impact.previous.content)
            if impact.previous
            else None
        ),
        targets=impact.targets,
        excluded=impact.excluded,
        document_targets=impact.document_targets,
        document_excluded=impact.document_excluded,
        missing_variables=impact.missing_variables,
    )


# --- 실행 --------------------------------------------------------------------------


def _fail(item: BulkUpdateItem, exc: AppError) -> None:
    item.status = BulkUpdateItemStatus.FAILED
    item.message = exc.message + "".join(f" {e.path}: {e.message}" for e in exc.errors)


def _publish_product(session: Session, job: BulkUpdateJob, item: BulkUpdateItem) -> None:
    """세이브포인트 안에서 상태를 재확인하고 새 문서 세트 버전을 만든다."""
    assert item.product_id is not None
    try:
        with session.begin_nested():
            product = get_product(session, item.product_id, for_update=True)
            if product.status != ProductStatus.ACTIVE:
                item.status = BulkUpdateItemStatus.SKIPPED
                item.message = f"실행 시 상태가 {product.status.value}여서 건너뛰었습니다."
                return
            published = latest_published(session, product.id)
            version = request_publication(
                session,
                product.id,
                job.change_reason,
                user_excluded_keys(published),
                batch_id=job.id,
            )
            item.status = BulkUpdateItemStatus.QUEUED
            item.document_set_version_id = version.id
            item.message = None
    except AppError as exc:
        _fail(item, exc)


def _fill_values(document: Document, used: list[str], fill: dict[str, str]) -> bool:
    """비어 있는 변수 값만 채운다. 문서에 이미 입력된 값은 덮어쓰지 않는다."""
    filled = {
        k: v.strip()
        for k, v in fill.items()
        if k in used and v.strip() and not document.variable_values.get(k)
    }
    if filled:
        document.variable_values = {**document.variable_values, **filled}
    return bool(filled)


def _apply_module(
    session: Session,
    job: BulkUpdateJob,
    item: BulkUpdateItem,
    document: Document,
    fill: dict[str, str],
) -> bool:
    """원본 그대로인 단락을 새 리비전으로 바꾼다. 발행할 것이 없으면 False."""
    assert job.clause is not None and job.clause_revision is not None
    reason = (
        f"공통 모듈 {job.clause.title} r{job.clause_revision.revision_no} 반영: {job.change_reason}"
    )
    filled = _fill_values(
        document, _used_keys_after(document, job.clause.id, job.clause_revision), fill
    )
    changed = document_service.apply_module_revision(
        session, document, job.clause.id, job.clause_revision, reason
    )
    if filled and not changed:
        document_service.record_revision(session, document, "일괄 반영 중 변수 값 입력")
    # 다시 시도할 때는 본문이 이미 반영되어 있으므로 발행만 한다.
    uses_revision = any(
        b.clause_id == job.clause_id
        and b.content_json is None
        and b.clause_revision_id == job.clause_revision_id
        for b in document.blocks
    )
    if not changed and not uses_revision:
        item.status = BulkUpdateItemStatus.SKIPPED
        item.message = "반영할 단락이 없습니다 (그사이 수정 또는 반영됨)."
        return False
    return True


def _apply_variable(
    session: Session,
    job: BulkUpdateJob,
    item: BulkUpdateItem,
    document: Document,
    fill: dict[str, str],
) -> bool:
    """새 기본값이 들어간 문서 리비전을 남긴다. 발행할 것이 없으면 False."""
    assert job.variable is not None
    key = job.variable.key
    overwrite = str(document.id) in job.target_snapshot.get("overwrite_document_ids", [])
    if document.variable_values.get(key):
        if not overwrite:
            item.status = BulkUpdateItemStatus.SKIPPED
            item.message = "문서에 따로 입력한 값을 유지했습니다."
            return False
        document.variable_values = {k: v for k, v in document.variable_values.items() if k != key}
    _fill_values(document, _used_keys(document), fill)
    snapshot = document_service.latest_revision(session, document.id).snapshot
    stored = snapshot.get("variables", {}).get(key, {}).get("default")
    values_changed = snapshot.get("variable_values", {}) != document.variable_values
    if stored != job.variable.default_value or values_changed:
        document_service.record_revision(session, document, job.change_reason)
    return True


def _publish_document(
    session: Session, job: BulkUpdateJob, item: BulkUpdateItem, fill: dict[str, str]
) -> None:
    """세이브포인트 안에서 상태를 재확인하고 변경을 반영한 뒤 발행한다."""
    assert item.document_id is not None
    try:
        with session.begin_nested():
            document = document_service.get_document(session, item.document_id, for_update=True)
            if document.status != DocumentStatus.ACTIVE:
                item.status = BulkUpdateItemStatus.SKIPPED
                item.message = f"실행 시 상태가 {document.status.value}여서 건너뛰었습니다."
                return
            apply = _apply_variable if job.variable_id else _apply_module
            if not apply(session, job, item, document, fill):
                return
    except AppError as exc:
        _fail(item, exc)
        return

    # 반영과 발행을 나눈다. 비어 있는 변수 값 등으로 발행만 못 해도 반영한 내용은 남긴다.
    snapshot = document_service.latest_revision(session, document.id).snapshot
    missing = missing_variables(snapshot)
    if missing:
        labels = ", ".join(f"[{snapshot['variables'][k]['label']}]" for k in missing)
        done = "새 값은 저장했지만" if job.variable_id else "본문은 반영했지만"
        item.status = BulkUpdateItemStatus.FAILED
        item.message = (
            f"{done} {labels} 값이 비어 있어 발행하지 못했습니다. "
            "위 칸에 값을 입력하고 [다시 시도]를 누르세요."
        )
        return
    try:
        with session.begin_nested():
            publication = publication_service.request_publication(
                session, document.id, job.change_reason, batch_id=job.id
            )
            item.status = BulkUpdateItemStatus.QUEUED
            item.publication_id = publication.id
            item.message = None
    except AppError as exc:
        _fail(item, exc)


def _queue(item: BulkUpdateItem, queue: RenderQueue) -> None:
    if item.status != BulkUpdateItemStatus.QUEUED:
        return
    if item.document_set_version_id:
        queue.versions.append(item.document_set_version_id)
    if item.publication_id:
        queue.publications.append(item.publication_id)


def create_job(session: Session, data: BulkUpdateCreate) -> tuple[BulkUpdateJob, RenderQueue]:
    """(작업, 렌더링 대상). 같은 request_id면 기존 작업을 그대로 돌려준다."""
    existing = session.scalar(
        sa.select(BulkUpdateJob).where(BulkUpdateJob.request_id == data.request_id)
    )
    if existing is not None:
        if existing.clause_id is None or existing.clause_id != data.clause_id:
            raise ConflictError("다른 작업에 이미 쓰인 요청 ID입니다.", code="DUPLICATE_REQUEST")
        return existing, RenderQueue()

    # 실행 직전에 영향 분석을 다시 해 대상을 확정한다.
    impact = _analyze(session, data.clause_id, data.revision_no)
    job = BulkUpdateJob(
        request_id=data.request_id,
        clause_id=impact.clause.id,
        clause_revision_id=impact.revision.id,
        change_reason=data.change_reason,
        target_snapshot={
            "targets": [t.model_dump(mode="json") for t in impact.targets],
            "excluded": [e.model_dump(mode="json") for e in impact.excluded],
            "document_targets": [t.model_dump(mode="json") for t in impact.document_targets],
            "document_excluded": [e.model_dump(mode="json") for e in impact.document_excluded],
        },
    )
    session.add(job)
    session.flush()
    queue = RenderQueue()
    for target in impact.targets:
        item = BulkUpdateItem(
            job_id=job.id, product_id=target.product_id, status=BulkUpdateItemStatus.QUEUED
        )
        session.add(item)
        _publish_product(session, job, item)
        session.flush()
        _queue(item, queue)
    for doc_target in impact.document_targets:
        item = BulkUpdateItem(
            job_id=job.id, document_id=doc_target.document_id, status=BulkUpdateItemStatus.QUEUED
        )
        session.add(item)
        _publish_document(session, job, item, data.variable_values)
        session.flush()
        _queue(item, queue)
    return job, queue


def _used_keys(document: Document) -> list[str]:
    keys: dict[str, None] = {}
    for block in document.blocks:
        keys.update(
            dict.fromkeys(richtext.variable_keys(document_service.effective_content(block)))
        )
    return list(keys)


def _get_variable(session: Session, variable_id: uuid.UUID) -> Variable:
    variable = session.get(Variable, variable_id)
    if variable is None:
        raise NotFoundError("변수를 찾을 수 없습니다.")
    return variable


def analyze_variable(session: Session, variable_id: uuid.UUID) -> VariableImpactOut:
    """이 변수를 쓰는 문서를 반영 대상·직접 입력 문서·제외로 나눈다."""
    variable = _get_variable(session, variable_id)
    documents = session.scalars(
        sa.select(Document)
        .where(Document.deleted_at.is_(None))
        .options(selectinload(Document.blocks))
        .order_by(Document.title)
    ).all()
    publications = _latest_publication_nos(session)
    targets: list[ImpactDocument] = []
    own: list[ImpactDocument] = []
    excluded: list[ImpactDocument] = []
    for document in documents:
        if variable.key not in _used_keys(document):
            continue
        row = ImpactDocument(
            document_id=document.id,
            title=document.title,
            status=document.status,
            current_publication_no=publications.get(document.id),
            own_value=document.variable_values.get(variable.key) or None,
        )
        if document.status == DocumentStatus.ENDED:
            excluded.append(row.model_copy(update={"reason": DOC_ENDED_REASON}))
        elif document.status == DocumentStatus.DRAFT:
            excluded.append(row.model_copy(update={"reason": VAR_DRAFT_REASON}))
        elif row.own_value:
            own.append(row)
        else:
            snapshot = document_service.latest_revision(session, document.id).snapshot
            stored = snapshot.get("variables", {}).get(variable.key, {}).get("default")
            if stored == variable.default_value:
                excluded.append(row.model_copy(update={"reason": VAR_UP_TO_DATE_REASON}))
            else:
                targets.append(row)
    return VariableImpactOut(
        variable_id=variable.id,
        key=variable.key,
        label=variable.label,
        value=variable.default_value,
        document_targets=targets,
        own_value_documents=own,
        document_excluded=excluded,
    )


def _latest_publication_nos(session: Session) -> dict[uuid.UUID, int]:
    rows = session.execute(
        sa.select(Publication.document_id, sa.func.max(Publication.version_no))
        .where(Publication.status == DocumentSetStatus.PUBLISHED)
        .group_by(Publication.document_id)
    ).all()
    return {document_id: no for document_id, no in rows}


def create_variable_job(
    session: Session, variable_id: uuid.UUID, data: VariableBulkUpdateCreate
) -> tuple[BulkUpdateJob, RenderQueue]:
    """변수의 현재 기본값을 사용 중 문서에 반영해 다시 발행한다."""
    existing = session.scalar(
        sa.select(BulkUpdateJob).where(BulkUpdateJob.request_id == data.request_id)
    )
    if existing is not None:
        if existing.variable_id != variable_id:
            raise ConflictError("다른 작업에 이미 쓰인 요청 ID입니다.", code="DUPLICATE_REQUEST")
        return existing, RenderQueue()

    impact = analyze_variable(session, variable_id)
    chosen = {str(i) for i in data.overwrite_document_ids}
    overwrite = [d for d in impact.own_value_documents if str(d.document_id) in chosen]
    kept = [
        d.model_copy(update={"reason": f"문서에 입력한 값({d.own_value})을 유지합니다."})
        for d in impact.own_value_documents
        if str(d.document_id) not in chosen
    ]
    targets = impact.document_targets + overwrite
    job = BulkUpdateJob(
        request_id=data.request_id,
        variable_id=impact.variable_id,
        variable_value=impact.value,
        change_reason=f"변수 [{impact.label}] 값 변경: {impact.value or '(비움)'}",
        target_snapshot={
            "targets": [],
            "excluded": [],
            "document_targets": [t.model_dump(mode="json") for t in targets],
            "document_excluded": [
                e.model_dump(mode="json") for e in kept + impact.document_excluded
            ],
            "overwrite_document_ids": [str(d.document_id) for d in overwrite],
        },
    )
    session.add(job)
    session.flush()
    queue = RenderQueue()
    for target in targets:
        item = BulkUpdateItem(
            job_id=job.id, document_id=target.document_id, status=BulkUpdateItemStatus.QUEUED
        )
        session.add(item)
        _publish_document(session, job, item, {})
        session.flush()
        _queue(item, queue)
    return job, queue


def retry_job(
    session: Session, job_id: uuid.UUID, data: BulkUpdateRetry | None = None
) -> tuple[BulkUpdateJob, RenderQueue]:
    """실패한 대상만 다시 처리한다. 성공·진행 중·건너뛴 대상은 건드리지 않는다.

    data.variable_values: 값이 비어 실패한 문서에 넣을 변수 값.
    """
    fill = data.variable_values if data else {}
    job = _get_job(session, job_id)
    queue = RenderQueue()
    for item in job.items:
        result, _ = _item_result(item)
        if result != "FAILED":
            continue
        try:
            with session.begin_nested():
                if item.document_set_version is not None:
                    retry_failed_version(session, item.document_set_version.id)
                    queue.versions.append(item.document_set_version.id)
                elif item.publication is not None:
                    publication_service.retry_failed(session, item.publication.id)
                    queue.publications.append(item.publication.id)
                elif item.product_id is not None:
                    _publish_product(session, job, item)
                    _queue(item, queue)
                else:
                    _publish_document(session, job, item, fill)
                    _queue(item, queue)
        except AppError as exc:
            item.message = exc.message
    session.flush()
    return job, queue


# --- 조회 --------------------------------------------------------------------------


def _get_job(session: Session, job_id: uuid.UUID) -> BulkUpdateJob:
    job = session.scalar(
        sa.select(BulkUpdateJob)
        .where(BulkUpdateJob.id == job_id)
        .options(selectinload(BulkUpdateJob.items))
        .execution_options(populate_existing=True)
    )
    if job is None:
        raise NotFoundError("일괄 수정 작업을 찾을 수 없습니다.")
    return job


def _item_result(item: BulkUpdateItem) -> tuple[ItemResult, str | None]:
    if item.status == BulkUpdateItemStatus.SKIPPED:
        return "SKIPPED", item.message
    output = item.document_set_version or item.publication
    if output is None:
        return "FAILED", item.message
    if output.status == DocumentSetStatus.PENDING:
        return "RUNNING", None
    if output.status == DocumentSetStatus.PUBLISHED:
        return "SUCCEEDED", None
    if item.product is not None and item.product.status == ProductStatus.ENDED:
        return "SKIPPED", "렌더링 전에 판매 종료되어 발행하지 않았습니다."
    if item.document is not None and item.document.status == DocumentStatus.ENDED:
        return "SKIPPED", "렌더링 전에 문서가 종료되어 발행하지 않았습니다."
    return "FAILED", output.failure_reason


def _summary(job: BulkUpdateJob) -> BulkUpdateSummary:
    results = [_item_result(i)[0] for i in job.items]
    counts = BulkUpdateCounts(
        total=len(results),
        running=results.count("RUNNING"),
        succeeded=results.count("SUCCEEDED"),
        failed=results.count("FAILED"),
        skipped=results.count("SKIPPED"),
    )
    return BulkUpdateSummary(
        id=job.id,
        request_id=job.request_id,
        kind="VARIABLE" if job.variable_id else "MODULE",
        clause_id=job.clause_id,
        clause_key=job.clause.clause_key if job.clause else None,
        clause_title=job.clause.title if job.clause else None,
        revision_no=job.clause_revision.revision_no if job.clause_revision else None,
        variable_id=job.variable_id,
        variable_label=job.variable.label if job.variable else None,
        variable_value=job.variable_value,
        change_reason=job.change_reason,
        created_at=job.created_at,
        finished=counts.running == 0,
        counts=counts,
    )


def _item_out(item: BulkUpdateItem) -> BulkUpdateItemOut:
    result, message = _item_result(item)
    if item.product is not None:
        version = item.document_set_version
        return BulkUpdateItemOut(
            target_type="PRODUCT",
            target_id=item.product.id,
            code=item.product.product_code,
            name=item.product.name,
            result=result,
            message=message,
            version_id=version.id if version else None,
            version_no=version.version_no if version else None,
        )
    assert item.document is not None
    publication = item.publication
    return BulkUpdateItemOut(
        target_type="DOCUMENT",
        target_id=item.document.id,
        code=None,
        name=item.document.title,
        result=result,
        message=message,
        version_id=publication.id if publication else None,
        version_no=publication.version_no if publication else None,
    )


def _missing_in_failed(session: Session, job: BulkUpdateJob) -> list[MissingVariable]:
    """값이 비어 발행하지 못한 문서의 변수."""
    missing: dict[str, int] = {}
    for item in job.items:
        if item.document is None or item.publication is not None:
            continue
        if _item_result(item)[0] != "FAILED" or item.document.status != DocumentStatus.ACTIVE:
            continue
        snapshot = document_service.latest_revision(session, item.document.id).snapshot
        for key in missing_variables(snapshot):
            missing[key] = missing.get(key, 0) + 1
    return _count_missing(session, missing)


def job_detail(session: Session, job_id: uuid.UUID) -> BulkUpdateDetail:
    session.expire_all()  # worker가 바꾼 버전 상태를 다시 읽는다.
    job = _get_job(session, job_id)
    snapshot = job.target_snapshot
    return BulkUpdateDetail(
        **_summary(job).model_dump(),
        items=[_item_out(i) for i in job.items],
        excluded=[ImpactProduct.model_validate(e) for e in snapshot.get("excluded", [])],
        document_excluded=[
            ImpactDocument.model_validate(e) for e in snapshot.get("document_excluded", [])
        ],
        missing_variables=_missing_in_failed(session, job),
    )


def list_jobs(session: Session) -> Sequence[BulkUpdateSummary]:
    jobs = session.scalars(
        sa.select(BulkUpdateJob)
        .options(selectinload(BulkUpdateJob.items))
        .order_by(BulkUpdateJob.created_at.desc())
    ).all()
    return [_summary(j) for j in jobs]
