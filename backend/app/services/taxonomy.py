"""카테고리·태그·변수와 본문 검증 (모듈·문서 공용)."""

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.orm import Session

from app import richtext
from app.errors import ConflictError, FieldError, NotFoundError, ValidationFailed
from app.models import (
    Category,
    Clause,
    ClauseRevision,
    Document,
    DocumentBlock,
    DocumentStatus,
    Tag,
    Variable,
    clause_tags,
    document_tags,
)
from app.rendering.rules import PLACEHOLDER, PLACEHOLDER_VARIABLES
from app.schemas.kms import (
    CategoryCreate,
    CategoryUpdate,
    TagOut,
    VariableCreate,
    VariableUpdate,
)

# --- 카테고리 ----------------------------------------------------------------------


def list_categories(session: Session) -> Sequence[Category]:
    return session.scalars(sa.select(Category).order_by(Category.sort_order, Category.name)).all()


def get_category(session: Session, category_id: uuid.UUID) -> Category:
    category = session.get(Category, category_id)
    if category is None:
        raise NotFoundError("카테고리를 찾을 수 없습니다.")
    return category


def require_category(session: Session, category_id: uuid.UUID | None) -> None:
    if category_id is not None and session.get(Category, category_id) is None:
        raise ValidationFailed(
            [FieldError(path="category_id", message="존재하지 않는 카테고리입니다.")]
        )


def category_and_descendants(session: Session, category_id: uuid.UUID) -> list[uuid.UUID]:
    rows = session.execute(sa.select(Category.id, Category.parent_id)).all()
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for cid, parent in rows:
        children.setdefault(parent, []).append(cid)
    out, stack = [], [category_id]
    while stack:
        cid = stack.pop()
        out.append(cid)
        stack.extend(children.get(cid, []))
    return out


def create_category(session: Session, data: CategoryCreate) -> Category:
    require_category(session, data.parent_id)
    _check_unique_name(session, data.parent_id, data.name)
    category = Category(name=data.name, parent_id=data.parent_id, sort_order=data.sort_order)
    session.add(category)
    session.flush()
    return category


def _check_unique_name(
    session: Session, parent_id: uuid.UUID | None, name: str, exclude: uuid.UUID | None = None
) -> None:
    stmt = sa.select(Category.id).where(
        Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id,
        Category.name == name,
    )
    if exclude is not None:
        stmt = stmt.where(Category.id != exclude)
    if session.scalar(stmt):
        raise ConflictError(
            "같은 위치에 같은 이름의 카테고리가 있습니다.", code="DUPLICATE_CATEGORY"
        )


def update_category(session: Session, category_id: uuid.UUID, data: CategoryUpdate) -> Category:
    category = get_category(session, category_id)
    parent_id = None if data.move_to_root else (data.parent_id or category.parent_id)
    if parent_id is not None:
        require_category(session, parent_id)
        if parent_id in category_and_descendants(session, category.id):
            raise ValidationFailed(
                [
                    FieldError(
                        path="parent_id",
                        message="자기 자신이나 하위 카테고리 아래로 옮길 수 없습니다.",
                    )
                ]
            )
    name = data.name or category.name
    _check_unique_name(session, parent_id, name, exclude=category.id)
    category.name, category.parent_id = name, parent_id
    if data.sort_order is not None:
        category.sort_order = data.sort_order
    session.flush()
    return category


def delete_category(session: Session, category_id: uuid.UUID) -> None:
    category = get_category(session, category_id)
    in_use = (
        session.scalar(sa.select(sa.func.count()).where(Category.parent_id == category.id))
        or session.scalar(sa.select(sa.func.count()).where(Clause.category_id == category.id))
        or session.scalar(sa.select(sa.func.count()).where(Document.category_id == category.id))
    )
    if in_use:
        raise ConflictError(
            "하위 카테고리·템플릿·문서가 있는 카테고리는 지울 수 없습니다.", code="CATEGORY_IN_USE"
        )
    session.delete(category)
    session.flush()


# --- 태그 --------------------------------------------------------------------------


def resolve_tags(session: Session, names: Iterable[str]) -> list[Tag]:
    """이름으로 태그를 찾고 없으면 만든다. 대소문자·공백은 그대로 둔다."""
    unique = list(dict.fromkeys(n.strip() for n in names if n.strip()))
    existing = {
        t.name: t for t in session.scalars(sa.select(Tag).where(Tag.name.in_(unique))).all()
    }
    tags = []
    for name in unique:
        tag = existing.get(name)
        if tag is None:
            tag = Tag(name=name)
            session.add(tag)
        tags.append(tag)
    return tags


def list_tags(session: Session) -> list[TagOut]:
    module_count = (
        sa.select(sa.func.count()).where(clause_tags.c.tag_id == Tag.id).scalar_subquery()
    )
    document_count = (
        sa.select(sa.func.count()).where(document_tags.c.tag_id == Tag.id).scalar_subquery()
    )
    rows = session.execute(
        sa.select(Tag.name, module_count, document_count).order_by(Tag.name)
    ).all()
    return [TagOut(name=n, module_count=m, document_count=d) for n, m, d in rows if m or d]


# --- 변수 --------------------------------------------------------------------------


def list_variables(session: Session) -> Sequence[Variable]:
    return session.scalars(
        sa.select(Variable).where(Variable.deleted_at.is_(None)).order_by(Variable.label)
    ).all()


def variables_by_key(session: Session, keys: Iterable[str] | None = None) -> dict[str, Variable]:
    stmt = sa.select(Variable)
    if keys is not None:
        stmt = stmt.where(Variable.key.in_(list(keys)))
    return {v.key: v for v in session.scalars(stmt).all()}


def create_variable(session: Session, data: VariableCreate) -> Variable:
    if data.key in PLACEHOLDER_VARIABLES:
        raise ConflictError("상품 문서용 예약 치환 항목 키입니다.", code="RESERVED_VARIABLE")
    if session.scalar(sa.select(Variable.id).where(Variable.key == data.key)):
        raise ConflictError("이미 존재하는 치환 항목 키입니다.", code="DUPLICATE_VARIABLE")
    variable = Variable(**data.model_dump())
    session.add(variable)
    session.flush()
    return variable


def _get_variable(session: Session, variable_id: uuid.UUID) -> Variable:
    variable = session.get(Variable, variable_id)
    if variable is None or variable.deleted_at is not None:
        raise NotFoundError("치환 항목을 찾을 수 없습니다.")
    return variable


def update_variable(session: Session, variable_id: uuid.UUID, data: VariableUpdate) -> Variable:
    variable = _get_variable(session, variable_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(variable, field, value)
    session.flush()
    return variable


# 서식 본문 JSON 안의 변수 칩 {"type": "variable", "attrs": {"key": ...}} 을 찾는 JSONPath
_CHIP_PATH = '$.** ? (@.type == "variable" && @.attrs.key == $key)'


def _uses_variable(column: Any, key: str) -> Any:
    return sa.func.jsonb_path_exists(
        column, sa.cast(_CHIP_PATH, JSONPATH), sa.func.jsonb_build_object("key", key)
    )


def name_list(names: Sequence[str]) -> str:
    """오류 안내용: 이름을 5개까지 보여 준다."""
    shown = ", ".join(names[:5])
    return shown + (f" 외 {len(names) - 5}개" if len(names) > 5 else "")


def delete_variable(session: Session, variable_id: uuid.UUID) -> None:
    """지금 쓰는 곳이 없는 변수만 삭제한다.

    지금 쓰는 곳: 삭제하지 않은 모듈의 최신 본문, 종료하지 않은 문서의 단락 본문과 입력값.
    예전 모듈 버전·종료 문서·발행본은 그대로 두고, 이름 표시를 위해 행은 남긴다(숨김).
    """
    variable = _get_variable(session, variable_id)
    key = variable.key
    latest = (
        sa.select(ClauseRevision.clause_id, sa.func.max(ClauseRevision.revision_no).label("no"))
        .group_by(ClauseRevision.clause_id)
        .subquery()
    )
    modules = session.scalars(
        sa.select(Clause.title)
        .join(latest, latest.c.clause_id == Clause.id)
        .join(
            ClauseRevision,
            sa.and_(
                ClauseRevision.clause_id == Clause.id, ClauseRevision.revision_no == latest.c.no
            ),
        )
        .where(Clause.deleted_at.is_(None), _uses_variable(ClauseRevision.content_json, key))
        .order_by(Clause.title)
    ).all()
    # 원본 그대로인 모듈 단락은 단락이 가리키는 모듈 버전의 본문을 본다.
    block_uses = sa.or_(
        _uses_variable(DocumentBlock.content_json, key),
        sa.and_(
            DocumentBlock.content_json.is_(None),
            DocumentBlock.clause_revision_id.in_(
                sa.select(ClauseRevision.id).where(_uses_variable(ClauseRevision.content_json, key))
            ),
        ),
    )
    documents = session.scalars(
        sa.select(Document.title)
        .where(
            Document.status != DocumentStatus.ENDED,
            Document.deleted_at.is_(None),
            sa.or_(
                Document.blocks.any(block_uses),
                Document.variable_values.has_key(key),
            ),
        )
        .order_by(Document.title)
    ).all()
    if modules or documents:
        where = []
        if modules:
            where.append(f"템플릿 {len(modules)}개({name_list(modules)})")
        if documents:
            where.append(f"문서 {len(documents)}개({name_list(documents)})")
        raise ConflictError(
            f"{' · '.join(where)}에서 쓰고 있어 지울 수 없습니다. "
            "본문에서 이 치환 항목을 먼저 빼세요.",
            code="VARIABLE_IN_USE",
        )
    variable.deleted_at = sa.func.now()
    session.flush()


def variable_labels(session: Session, *, active_only: bool = False) -> dict[str, str]:
    """변수 키 → 이름. active_only: 새 본문에 쓸 수 있는(삭제하지 않은) 변수만."""
    stmt = sa.select(Variable)
    if active_only:
        stmt = stmt.where(Variable.deleted_at.is_(None))
    labels = dict(PLACEHOLDER_VARIABLES)
    labels.update({v.key: v.label for v in session.scalars(stmt).all()})
    return labels


# --- 본문 검증 ---------------------------------------------------------------------


def validate_body(
    session: Session,
    content: str | None,
    content_json: dict[str, Any] | None,
    path: str = "",
) -> tuple[str, dict[str, Any] | None]:
    """(검색용 일반 텍스트, 서식 본문)을 돌려준다. 둘 중 하나만 받아야 한다.

    변수는 정의된 변수(variables) 또는 상품 문서 예약 변수(product.*, company.*)만 허용한다.
    """
    prefix = f"{path}." if path else ""
    if (content is None) == (content_json is None):
        raise ValidationFailed(
            [
                FieldError(
                    path=f"{prefix}content", message="content 또는 content_json 중 하나만 보내세요."
                )
            ]
        )
    labels = variable_labels(session)
    active = variable_labels(session, active_only=True)
    if content_json is not None:
        content_json = richtext.normalize(content_json)
        errors = richtext.validate(content_json, f"{prefix}content_json")
        if not errors:
            unknown = [k for k in richtext.variable_keys(content_json) if k not in active]
            errors = [
                FieldError(
                    path=f"{prefix}content_json", message=f"정의되지 않은 치환 항목입니다: {k}"
                )
                for k in unknown
            ]
        if errors:
            raise ValidationFailed(errors)
        plain = richtext.to_plain(content_json, labels)
        if not plain.strip():
            raise ValidationFailed(
                [FieldError(path=f"{prefix}content_json", message="본문이 비어 있습니다.")]
            )
        return plain, content_json
    assert content is not None
    unknown = [k for k in PLACEHOLDER.findall(content) if k not in labels]
    if unknown:
        raise ValidationFailed(
            [
                FieldError(path=f"{prefix}content", message=f"정의되지 않은 치환 항목입니다: {k}")
                for k in unknown
            ]
        )
    return content, None
