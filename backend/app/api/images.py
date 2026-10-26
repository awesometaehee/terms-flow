import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app import assets
from app.db import get_session
from app.errors import ERROR_RESPONSES
from app.schemas.common import NonBlankStr, RequestModel
from app.services import images

router = APIRouter(tags=["images"])
SessionDep = Annotated[Session, Depends(get_session)]


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    # 본문 이미지 노드의 src
    url: str
    content_type: str
    size_bytes: int
    width: int | None
    height: int | None
    created_at: datetime


class ImageRename(RequestModel):
    name: NonBlankStr


@router.get("/images")
def list_images(session: SessionDep, q: str | None = None) -> list[ImageOut]:
    """자료실 이미지 (최근 올린 것부터). q: 이름 검색."""
    return [ImageOut.model_validate(i) for i in images.list_images(session, q)]


@router.post(
    "/images",
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                t: {"schema": {"type": "string", "format": "binary"}}
                for t in assets.BY_CONTENT_TYPE
            },
        }
    },
)
async def upload_image(request: Request, session: SessionDep) -> ImageOut:
    """이미지 올리기. 본문에 파일 그대로, Content-Type에 이미지 형식, X-File-Name에 파일 이름
    (encodeURIComponent)을 넣는다. PNG·JPG·GIF·WEBP, 10MB까지.
    """
    data = await request.body()
    name = unquote(request.headers.get("x-file-name", ""))
    image = images.upload(session, data, request.headers.get("content-type", ""), name)
    session.commit()
    return ImageOut.model_validate(image)


@router.patch("/images/{image_id}", responses=ERROR_RESPONSES)
def rename_image(image_id: uuid.UUID, data: ImageRename, session: SessionDep) -> ImageOut:
    image = images.rename(session, image_id, data.name)
    session.commit()
    return ImageOut.model_validate(image)


@router.delete(
    "/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERROR_RESPONSES
)
def delete_image(image_id: uuid.UUID, session: SessionDep) -> None:
    """자료실에서 지운다 (파일은 남긴다). 템플릿·문서에서 쓰고 있으면 409 IMAGE_IN_USE."""
    images.delete(session, image_id)
    session.commit()


@router.get("/images/{image_id}/download", responses=ERROR_RESPONSES)
def download_image(image_id: uuid.UUID, session: SessionDep) -> StreamingResponse:
    """원본 파일을 올린 이름으로 내려받는다."""
    image = images.get_image(session, image_id)
    fh, name = images.open_file(image)

    def chunks() -> Iterator[bytes]:
        with fh:
            while chunk := fh.read(64 * 1024):
                yield chunk

    return StreamingResponse(
        chunks(),
        media_type=image.content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )
