from collections.abc import Iterator

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import assets
from app.errors import ERROR_RESPONSES, NotFoundError
from app.storage import open_object

router = APIRouter(tags=["assets"])


class AssetOut(BaseModel):
    # 본문 이미지 노드의 src로 쓴다.
    url: str


@router.post(
    "/assets",
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
async def upload_asset(request: Request) -> AssetOut:
    """이미지 올리기. 요청 본문에 파일 그대로, Content-Type에 이미지 형식을 넣는다 (10MB까지)."""
    data = await request.body()
    return AssetOut(url=assets.save_image(data, request.headers.get("content-type", "")))


@router.get("/assets/{name}", responses=ERROR_RESPONSES)
def get_asset(name: str) -> StreamingResponse:
    try:
        key, content_type = assets.parse_name(name)
        fh = open_object(key)
    except (ValueError, FileNotFoundError):
        raise NotFoundError("이미지를 찾을 수 없습니다.") from None

    def chunks() -> Iterator[bytes]:
        with fh:
            while chunk := fh.read(64 * 1024):
                yield chunk

    # 같은 주소의 파일은 바뀌지 않는다.
    return StreamingResponse(
        chunks(),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
