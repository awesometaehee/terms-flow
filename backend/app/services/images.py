"""이미지 자료실.

올린 이미지는 저장소 assets/<파일>에 한 번 저장하고(본문에는 /api/assets/<파일> 주소로 들어간다),
자료실 목록에 이름·크기를 남긴다. 편집기에서 올리거나 붙여 넣은 이미지도 자료실에 쌓인다.
지우면 목록에서만 빠진다. 이전 본문·발행본이 쓰므로 파일은 남긴다.
"""

import io
import uuid
from collections.abc import Sequence
from pathlib import PurePath
from typing import Any, BinaryIO

import sqlalchemy as sa
from PIL import Image as PILImage
from sqlalchemy.orm import Session

from app import assets
from app.db import like_pattern
from app.errors import ConflictError, NotFoundError
from app.models import Clause, ClauseRevision, Document, DocumentBlock, DocumentStatus, Image
from app.services.taxonomy import name_list
from app.storage import open_object

MAX_NAME = 200


def _clean_name(name: str | None, ext: str) -> str:
    name = " ".join((name or "").split())[:MAX_NAME] or f"이미지.{ext}"
    return name


def upload(session: Session, data: bytes, content_type: str, file_name: str | None) -> Image:
    url = assets.save_image(data, content_type)
    ext = url.rsplit(".", 1)[-1]
    width = height = None
    try:
        with PILImage.open(io.BytesIO(data)) as picture:
            width, height = picture.size
    except Exception:  # 크기를 못 읽어도 올리기는 막지 않는다
        pass
    image = Image(
        name=_clean_name(file_name, ext),
        url=url,
        content_type=assets.TYPES[ext][0],
        size_bytes=len(data),
        width=width,
        height=height,
    )
    session.add(image)
    session.flush()
    return image


def get_image(session: Session, image_id: uuid.UUID) -> Image:
    image = session.get(Image, image_id)
    if image is None or image.deleted_at is not None:
        raise NotFoundError("이미지를 찾을 수 없습니다.")
    return image


def list_images(session: Session, q: str | None = None) -> Sequence[Image]:
    stmt = sa.select(Image).where(Image.deleted_at.is_(None)).order_by(Image.created_at.desc())
    if q and q.strip():
        stmt = stmt.where(Image.name.ilike(like_pattern(q.strip())))
    return session.scalars(stmt).all()


def rename(session: Session, image_id: uuid.UUID, name: str) -> Image:
    image = get_image(session, image_id)
    image.name = _clean_name(name, image.url.rsplit(".", 1)[-1])
    session.flush()
    return image


def usage(session: Session, url: str) -> tuple[list[str], list[str]]:
    """이 이미지를 지금 쓰는 템플릿(최신 본문)과 문서(작성 중·사용 중) 이름."""

    def contains(column: Any) -> sa.ColumnElement[bool]:
        return sa.cast(column, sa.Text).contains(url)

    latest = (
        sa.select(ClauseRevision.clause_id, sa.func.max(ClauseRevision.revision_no).label("no"))
        .group_by(ClauseRevision.clause_id)
        .subquery()
    )
    templates = session.scalars(
        sa.select(Clause.title)
        .join(latest, latest.c.clause_id == Clause.id)
        .join(
            ClauseRevision,
            sa.and_(
                ClauseRevision.clause_id == Clause.id, ClauseRevision.revision_no == latest.c.no
            ),
        )
        .where(Clause.deleted_at.is_(None), contains(ClauseRevision.content_json))
        .order_by(Clause.title)
    ).all()
    block_uses = sa.or_(
        contains(DocumentBlock.content_json),
        sa.and_(
            DocumentBlock.content_json.is_(None),
            DocumentBlock.clause_revision_id.in_(
                sa.select(ClauseRevision.id).where(contains(ClauseRevision.content_json))
            ),
        ),
    )
    documents = session.scalars(
        sa.select(Document.title)
        .where(
            Document.status != DocumentStatus.ENDED,
            Document.deleted_at.is_(None),
            Document.blocks.any(block_uses),
        )
        .order_by(Document.title)
    ).all()
    return list(templates), list(documents)


def delete(session: Session, image_id: uuid.UUID) -> None:
    image = get_image(session, image_id)
    templates, documents = usage(session, image.url)
    if templates or documents:
        where = []
        if templates:
            where.append(f"템플릿 {len(templates)}개({name_list(templates)})")
        if documents:
            where.append(f"문서 {len(documents)}개({name_list(documents)})")
        raise ConflictError(
            f"{' · '.join(where)}에서 쓰고 있어 지울 수 없습니다. "
            "본문에서 이 이미지를 먼저 빼세요.",
            code="IMAGE_IN_USE",
        )
    image.deleted_at = sa.func.now()
    session.flush()


def open_file(image: Image) -> tuple[BinaryIO, str]:
    """(파일, 내려받을 파일 이름). 이름에 확장자가 없으면 붙인다."""
    key, _ = assets.parse_name(image.url.rsplit("/", 1)[-1])
    ext = image.url.rsplit(".", 1)[-1]
    name = (
        image.name
        if PurePath(image.name).suffix.lower().lstrip(".") in (ext, "jpeg")
        else f"{image.name}.{ext}"
    )
    return open_object(key), name
