"""KMS 문서: 모듈·직접 쓴 단락의 조합, 문서 안 수정, 원본 반영, 리비전.

- 문서를 저장할 때마다 불변 리비전(document_revisions)을 남긴다. 리비전에는 단락의 실제 본문까지
  담아 이후 모듈이 바뀌어도 그대로 재현할 수 있다.
- 모듈 단락은 기준 리비전을 가리키고, 문서에서 고친 경우에만 수정본(content_json)을 갖는다.
- 종료(ENDED) 문서는 수정·상태 변경·발행을 거부한다 (DB 트리거로도 막는다).
"""

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, selectinload

from app import richtext
from app.db import like_pattern
from app.errors import ConflictError, FieldError, NotFoundError, ValidationFailed
from app.models import (
    BlockKind,
    Clause,
    ClauseRevision,
    Document,
    DocumentBlock,
    DocumentRevision,
    DocumentSetStatus,
    DocumentStatus,
    Publication,
    Tag,
)
from app.schemas.kms import (
    BlockIn,
    BlockOut,
    DocumentCreate,
    DocumentDetail,
    DocumentSave,
    DocumentStatusChange,
    DocumentSummary,
    PromoteBlock,
    VariableOut,
)
from app.services.taxonomy import (
    category_and_descendants,
    require_category,
    resolve_tags,
    validate_body,
    variable_labels,
    variables_by_key,
)

SNAPSHOT_SCHEMA_VERSION = 1
ALLOWED_TRANSITIONS: dict[DocumentStatus, set[DocumentStatus]] = {
    DocumentStatus.DRAFT: {DocumentStatus.ACTIVE},
    DocumentStatus.ACTIVE: {DocumentStatus.ENDED},
    DocumentStatus.ENDED: set(),
}


# --- 조회 --------------------------------------------------------------------------


def get_document(session: Session, document_id: uuid.UUID, *, for_update: bool = False) -> Document:
    stmt = (
        sa.select(Document)
        .where(Document.id == document_id, Document.deleted_at.is_(None))
        .options(selectinload(Document.blocks), selectinload(Document.tags))
    )
    if for_update:
        stmt = stmt.with_for_update(of=Document)
    document = session.scalar(stmt)
    if document is None:
        raise NotFoundError("문서를 찾을 수 없습니다.")
    return document


def delete_document(session: Session, document_id: uuid.UUID) -> None:
    """작성 중·사용 중 문서를 삭제(숨김)한다. 종료 문서는 보관 기록이라 지우지 않는다."""
    document = get_document(session, document_id, for_update=True)
    if document.status == DocumentStatus.ENDED:
        raise ConflictError(
            "종료된 문서는 보관 기록이라 삭제할 수 없습니다.", code="DOCUMENT_ENDED"
        )
    document.deleted_at = sa.func.now()
    session.flush()


def ensure_not_ended(document: Document) -> None:
    if document.status == DocumentStatus.ENDED:
        raise ConflictError("종료된 문서는 수정하거나 발행할 수 없습니다.", code="DOCUMENT_ENDED")


def _check_lock(document: Document, lock_version: int) -> None:
    if document.lock_version != lock_version:
        raise ConflictError(
            "다른 사용자가 먼저 저장했습니다. 최신 내용을 다시 불러오세요.", code="VERSION_CONFLICT"
        )


def _latest_revision_no(session: Session, document_id: uuid.UUID) -> int:
    return (
        session.scalar(
            sa.select(sa.func.max(DocumentRevision.revision_no)).where(
                DocumentRevision.document_id == document_id
            )
        )
        or 0
    )


def latest_revision(session: Session, document_id: uuid.UUID) -> DocumentRevision:
    revision = session.scalar(
        sa.select(DocumentRevision)
        .where(DocumentRevision.document_id == document_id)
        .order_by(DocumentRevision.revision_no.desc())
        .limit(1)
    )
    if revision is None:
        raise NotFoundError("문서 리비전이 없습니다.")
    return revision


def _latest_clause_revision_nos(
    session: Session, clause_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not clause_ids:
        return {}
    rows = session.execute(
        sa.select(ClauseRevision.clause_id, sa.func.max(ClauseRevision.revision_no))
        .where(ClauseRevision.clause_id.in_(set(clause_ids)))
        .group_by(ClauseRevision.clause_id)
    ).all()
    return dict(rows)


def effective_content(block: DocumentBlock) -> dict[str, Any]:
    if block.content_json is not None:
        return block.content_json
    assert block.clause_revision is not None
    return block.clause_revision.rich


def _latest_publication_nos(
    session: Session, document_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not document_ids:
        return {}
    rows = session.execute(
        sa.select(Publication.document_id, sa.func.max(Publication.version_no))
        .where(
            Publication.document_id.in_(document_ids),
            Publication.status == DocumentSetStatus.PUBLISHED,
        )
        .group_by(Publication.document_id)
    ).all()
    return dict(rows)


def _summary(
    document: Document, revision_no: int, latest_publication: int | None
) -> dict[str, Any]:
    return {
        "id": document.id,
        "title": document.title,
        "status": document.status,
        "category_id": document.category_id,
        "tags": [t.name for t in document.tags],
        "block_count": len(document.blocks),
        "revision_no": revision_no,
        "latest_publication_no": latest_publication,
        "updated_at": document.updated_at,
    }


def to_detail(session: Session, document: Document) -> DocumentDetail:
    latest = _latest_clause_revision_nos(
        session, [b.clause_id for b in document.blocks if b.clause_id]
    )
    blocks = []
    used_keys: dict[str, None] = {}
    for block in document.blocks:
        content = effective_content(block)
        for key in richtext.variable_keys(content):
            used_keys.setdefault(key, None)
        revision = block.clause_revision
        blocks.append(
            BlockOut(
                id=block.id,
                kind=block.kind,
                clause_id=block.clause_id,
                clause_key=block.clause.clause_key if block.clause else None,
                clause_title=block.clause.title if block.clause else None,
                clause_revision_no=revision.revision_no if revision else None,
                latest_revision_no=latest.get(block.clause_id) if block.clause_id else None,
                content_json=content,
                original_content_json=revision.rich if revision else None,
                modified=block.kind == BlockKind.MODULE and block.content_json is not None,
                outdated=bool(
                    revision
                    and block.clause_id
                    and latest.get(block.clause_id, 0) > revision.revision_no
                ),
            )
        )
    variables = variables_by_key(session, list(used_keys) + list(document.variable_values))
    pub = _latest_publication_nos(session, [document.id]).get(document.id)
    return DocumentDetail(
        **_summary(document, _latest_revision_no(session, document.id), pub),
        lock_version=document.lock_version,
        variable_values=document.variable_values,
        variables=[
            VariableOut.model_validate(v) for v in sorted(variables.values(), key=lambda v: v.label)
        ],
        blocks=blocks,
    )


def list_documents(
    session: Session,
    *,
    status: DocumentStatus | None = None,
    category_id: uuid.UUID | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[DocumentSummary]:
    stmt = (
        sa.select(Document)
        .where(Document.deleted_at.is_(None))
        .options(selectinload(Document.blocks), selectinload(Document.tags))
        .order_by(Document.updated_at.desc())
    )
    if status is not None:
        stmt = stmt.where(Document.status == status)
    if category_id is not None:
        stmt = stmt.where(Document.category_id.in_(category_and_descendants(session, category_id)))
    if tag:
        stmt = stmt.where(Document.tags.any(Tag.name == tag))
    if q:
        pattern = like_pattern(q)
        stmt = stmt.where(
            sa.or_(Document.title.ilike(pattern), Document.search_text.ilike(pattern))
        )
    documents = session.scalars(stmt).all()
    ids = [d.id for d in documents]
    revisions = (
        dict(
            session.execute(
                sa.select(DocumentRevision.document_id, sa.func.max(DocumentRevision.revision_no))
                .where(DocumentRevision.document_id.in_(ids))
                .group_by(DocumentRevision.document_id)
            ).all()
        )
        if ids
        else {}
    )
    pubs = _latest_publication_nos(session, ids)
    return [
        DocumentSummary(**_summary(d, revisions.get(d.id, 0), pubs.get(d.id))) for d in documents
    ]


# --- 스냅샷·리비전 -----------------------------------------------------------------


def build_snapshot(session: Session, document: Document) -> dict[str, Any]:
    """문서를 그대로 재현할 수 있는 스냅샷 (단락 본문·변수 이름·기본값 포함)."""
    blocks = []
    keys: dict[str, None] = {}
    for block in document.blocks:
        content = effective_content(block)
        for key in richtext.variable_keys(content):
            keys.setdefault(key, None)
        revision = block.clause_revision
        blocks.append(
            {
                "id": str(block.id),
                "kind": block.kind.value,
                "clause_id": str(block.clause_id) if block.clause_id else None,
                "clause_key": block.clause.clause_key if block.clause else None,
                "clause_title": block.clause.title if block.clause else None,
                "clause_revision_id": str(revision.id) if revision else None,
                "clause_revision_no": revision.revision_no if revision else None,
                "modified": block.kind == BlockKind.MODULE and block.content_json is not None,
                "content_json": content,
            }
        )
    labels = variable_labels(session)
    definitions = variables_by_key(session, keys)
    return {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "title": document.title,
        "variable_values": dict(document.variable_values),
        "variables": {
            key: {
                "label": labels.get(key, key),
                "default": definitions[key].default_value if key in definitions else None,
            }
            for key in keys
        },
        "blocks": blocks,
    }


def _search_text(session: Session, document: Document) -> str:
    labels = variable_labels(session)
    texts = [richtext.to_plain(effective_content(b), labels) for b in document.blocks]
    return "\n\n".join(t for t in texts if t)


def _add_revision(session: Session, document: Document, reason: str) -> DocumentRevision:
    session.flush()
    # 단락의 기준 리비전(FK)이 바뀌었을 수 있으므로 단락 객체까지 다시 읽는다.
    for block in list(document.blocks):
        session.expire(block)
    session.expire(document, ["blocks"])
    revision = DocumentRevision(
        document_id=document.id,
        revision_no=_latest_revision_no(session, document.id) + 1,
        snapshot=build_snapshot(session, document),
        change_reason=reason,
    )
    document.search_text = _search_text(session, document)
    session.add(revision)
    session.flush()
    return revision


def list_revisions(session: Session, document_id: uuid.UUID) -> Sequence[DocumentRevision]:
    get_document(session, document_id)
    return session.scalars(
        sa.select(DocumentRevision)
        .where(DocumentRevision.document_id == document_id)
        .order_by(DocumentRevision.revision_no.desc())
    ).all()


def get_revision(session: Session, document_id: uuid.UUID, revision_no: int) -> DocumentRevision:
    revision = session.scalar(
        sa.select(DocumentRevision).where(
            DocumentRevision.document_id == document_id,
            DocumentRevision.revision_no == revision_no,
        )
    )
    if revision is None:
        raise NotFoundError("문서 리비전을 찾을 수 없습니다.")
    return revision


# --- 변경 --------------------------------------------------------------------------


def create_document(session: Session, data: DocumentCreate) -> Document:
    require_category(session, data.category_id)
    document = Document(
        title=data.title,
        category_id=data.category_id,
        status=DocumentStatus.DRAFT,
        variable_values={},
        tags=resolve_tags(session, data.tags),
    )
    session.add(document)
    session.flush()
    if data.copy_from_document_id is not None:
        source = get_document(session, data.copy_from_document_id)
        document.variable_values = dict(source.variable_values)
        for block in source.blocks:
            session.add(
                DocumentBlock(
                    id=uuid.uuid4(),
                    document_id=document.id,
                    position=block.position,
                    kind=block.kind,
                    clause_id=block.clause_id,
                    clause_revision_id=block.clause_revision_id,
                    content_json=block.content_json,
                )
            )
    _add_revision(
        session, document, "생성" if data.copy_from_document_id is None else "복제로 생성"
    )
    return document


def _build_blocks(
    session: Session, document: Document, blocks: Sequence[BlockIn]
) -> list[DocumentBlock]:
    errors: list[FieldError] = []
    ids = [b.id for b in blocks]
    duplicated = {i for i in ids if ids.count(i) > 1}
    taken = set(
        session.scalars(
            sa.select(DocumentBlock.id).where(
                DocumentBlock.id.in_(ids), DocumentBlock.document_id != document.id
            )
        ).all()
    )
    revisions = {
        (r.clause_id, r.revision_no): r
        for r in session.scalars(
            sa.select(ClauseRevision).where(
                ClauseRevision.clause_id.in_({b.clause_id for b in blocks if b.clause_id})
            )
        ).all()
    }
    # 삭제한 모듈은 새 단락으로 넣을 수 없다 (이미 있던 단락은 그대로 둔다).
    deleted = set(
        session.scalars(
            sa.select(Clause.id).where(
                Clause.id.in_({b.clause_id for b in blocks if b.clause_id}),
                Clause.deleted_at.is_not(None),
            )
        ).all()
    )
    existing_ids = {b.id for b in document.blocks}
    built: list[DocumentBlock] = []
    for i, block in enumerate(blocks):
        path = f"blocks[{i}]"
        if block.id in duplicated or block.id in taken:
            errors.append(FieldError(path=f"{path}.id", message="단락 ID가 중복됩니다."))
            continue
        try:
            if block.kind == BlockKind.MODULE:
                revision = (
                    revisions.get((block.clause_id, block.clause_revision_no))
                    if block.clause_id is not None and block.clause_revision_no is not None
                    else None
                )
                if revision is None:
                    errors.append(
                        FieldError(
                            path=f"{path}.clause_revision_no",
                            message="존재하지 않는 모듈 리비전입니다.",
                        )
                    )
                    continue
                if revision.clause_id in deleted and block.id not in existing_ids:
                    errors.append(
                        FieldError(path=f"{path}.clause_id", message="삭제된 모듈입니다.")
                    )
                    continue
                override = None
                # 에디터가 붙이는 빈 속성을 지우고 비교한다 (원본과 같으면 수정 아님).
                if block.content_json is not None and richtext.normalize(
                    block.content_json
                ) != richtext.normalize(revision.rich):
                    _, override = validate_body(session, None, block.content_json, path)
                built.append(
                    DocumentBlock(
                        id=block.id,
                        position=i,
                        kind=BlockKind.MODULE,
                        clause_id=revision.clause_id,
                        clause_revision_id=revision.id,
                        content_json=override,
                    )
                )
            else:
                if block.clause_id is not None or block.content_json is None:
                    errors.append(
                        FieldError(
                            path=path, message="직접 쓴 단락은 content_json만 보내야 합니다."
                        )
                    )
                    continue
                richtext_errors = richtext.validate(block.content_json, f"{path}.content_json")
                if richtext_errors:
                    errors += richtext_errors
                    continue
                labels = variable_labels(session)
                unknown = [k for k in richtext.variable_keys(block.content_json) if k not in labels]
                errors += [
                    FieldError(
                        path=f"{path}.content_json", message=f"정의되지 않은 변수입니다: {k}"
                    )
                    for k in unknown
                ]
                built.append(
                    DocumentBlock(
                        id=block.id,
                        position=i,
                        kind=BlockKind.TEXT,
                        content_json=richtext.normalize(block.content_json),
                    )
                )
        except ValidationFailed as exc:
            errors += exc.errors
    if errors:
        raise ValidationFailed(errors)
    return built


def save_document(session: Session, document_id: uuid.UUID, data: DocumentSave) -> Document:
    document = get_document(session, document_id, for_update=True)
    ensure_not_ended(document)
    _check_lock(document, data.lock_version)
    require_category(session, data.category_id)
    defined = set(variables_by_key(session, data.variable_values))
    unknown = [k for k in data.variable_values if k not in defined]
    if unknown:
        raise ValidationFailed(
            [
                FieldError(path=f"variable_values.{k}", message="정의되지 않은 변수입니다.")
                for k in unknown
            ]
        )
    new_blocks = _build_blocks(session, document, data.blocks)

    # 단락은 클라이언트 ID를 유지한 채 통째로 바꾼다.
    # 같은 ID로 다시 넣으므로 기존 객체를 세션에서 뗀다.
    for old in list(document.blocks):
        session.expunge(old)
    session.execute(sa.delete(DocumentBlock).where(DocumentBlock.document_id == document.id))
    session.expire(document, ["blocks"])
    for block in new_blocks:
        block.document_id = document.id
        session.add(block)
    document.title = data.title
    document.category_id = data.category_id
    document.tags = resolve_tags(session, data.tags)
    document.variable_values = {k: v for k, v in data.variable_values.items() if v != ""}
    document.updated_at = sa.func.now()  # 단락만 바뀌어도 lock_version을 올린다.
    _add_revision(session, document, data.change_reason)
    return document


def change_status(session: Session, document_id: uuid.UUID, data: DocumentStatusChange) -> Document:
    document = get_document(session, document_id, for_update=True)
    ensure_not_ended(document)
    if data.status not in ALLOWED_TRANSITIONS[document.status]:
        raise ConflictError(
            f"{document.status.value}에서 {data.status.value}(으)로 바꿀 수 없습니다.",
            code="INVALID_STATUS_TRANSITION",
        )
    _check_lock(document, data.lock_version)
    document.status = data.status
    session.flush()
    return document


def promote_block(
    session: Session, document_id: uuid.UUID, block_id: uuid.UUID, data: PromoteBlock
) -> ClauseRevision:
    """문서에서 고친 모듈 단락을 원본 모듈의 새 리비전으로 저장한다.

    단락은 그 리비전을 가리키고 문서 수정본은 지운다.
    """
    document = get_document(session, document_id, for_update=True)
    ensure_not_ended(document)
    _check_lock(document, data.lock_version)
    block = next((b for b in document.blocks if b.id == block_id), None)
    if block is None:
        raise NotFoundError("단락을 찾을 수 없습니다.")
    if block.kind != BlockKind.MODULE or block.content_json is None:
        raise ConflictError(
            "문서에서 수정한 모듈 단락만 원본에 반영할 수 있습니다.", code="NOT_MODIFIED"
        )
    assert block.clause_revision is not None and block.clause_id is not None
    clause = session.scalar(
        sa.select(Clause)
        .where(Clause.id == block.clause_id)
        .options(selectinload(Clause.revisions))
        .with_for_update(of=Clause)
    )
    assert clause is not None
    latest_no = clause.revisions[-1].revision_no
    if latest_no != block.clause_revision.revision_no:
        raise ConflictError(
            f"원본 모듈이 그사이 r{latest_no}으로 바뀌었습니다. "
            "최신 원본과 비교한 뒤 다시 반영하세요.",
            code="VERSION_CONFLICT",
        )
    content, content_json = validate_body(session, None, block.content_json)
    revision = ClauseRevision(
        clause_id=clause.id,
        revision_no=latest_no + 1,
        content=content,
        content_json=content_json,
        change_reason=data.change_reason,
    )
    session.add(revision)
    session.flush()
    block.clause_revision_id = revision.id
    block.content_json = None
    document.updated_at = sa.func.now()
    _add_revision(
        session,
        document,
        f"모듈 {clause.title} r{revision.revision_no}에 반영: {data.change_reason}",
    )
    return revision


def record_revision(session: Session, document: Document, reason: str) -> None:
    """본문 외 변경(변수 값 등)을 문서 리비전으로 남긴다."""
    document.updated_at = sa.func.now()
    _add_revision(session, document, reason)


def apply_module_revision(
    session: Session,
    document: Document,
    clause_id: uuid.UUID,
    revision: ClauseRevision,
    reason: str,
) -> int:
    """수정하지 않은 해당 모듈 단락을 새 리비전으로 바꾸고 문서 리비전을 남긴다.

    바꾼 단락 수를 돌려준다.
    """
    changed = 0
    for block in document.blocks:
        if (
            block.clause_id == clause_id
            and block.content_json is None
            and block.clause_revision_id != revision.id
        ):
            block.clause_revision_id = revision.id
            changed += 1
    if changed:
        document.updated_at = sa.func.now()
        _add_revision(session, document, reason)
    return changed
