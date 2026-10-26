from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app import pdf_tables
from app.errors import ERROR_RESPONSES

router = APIRouter(tags=["imports"])


class ImportedTable(BaseModel):
    page: int
    index: int
    rows: int
    cols: int
    # 본문에 그대로 넣을 수 있는 서식 본문 (표 + 빈 문단)
    content: dict[str, Any]
    preview_html: str


class PdfTablesOut(BaseModel):
    tables: list[ImportedTable]


@router.post(
    "/imports/pdf-tables",
    responses=ERROR_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def import_pdf_tables(request: Request) -> PdfTablesOut:
    """PDF에서 표를 찾아 본문 표로 바꿔 돌려준다 (저장하지 않는다). 칸 안 이미지는 assets에 올린다.

    요청 본문에 PDF 파일 그대로 (20MB, 앞 10쪽까지).
    """
    data = await request.body()
    tables = await run_in_threadpool(pdf_tables.extract_tables, data)
    return PdfTablesOut(tables=[ImportedTable.model_validate(t) for t in tables])
