"""서식 본문의 표·단 나누기·이미지. 모든 문구는 [샘플]이다."""

import struct
import uuid
import zlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import richtext
from app.models import DocumentSetStatus
from app.rendering.publisher import render_publication
from tests.helpers import renderer_available
from tests.kms_helpers import create_document, create_module, post, save, set_status, text


def para(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"type": "paragraph", "content": list(nodes)}


def cell(value: str, header: bool = False, **attrs: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "type": "tableHeader" if header else "tableCell",
        "content": [para(text(value))],
    }
    if attrs:
        node["attrs"] = attrs
    return node


def table(*rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "table", "content": [{"type": "tableRow", "content": r} for r in rows]}


def png_bytes() -> bytes:
    """2×2 빨간 PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 2 for _ in range(2))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


SAMPLE_TABLE = table(
    [cell("[샘플] 구분", header=True, colspan=2, background="#d9e2f3"), cell("내용", header=True)],
    [cell("[샘플] 고인용품", rowspan=2), cell("관"), cell("[샘플] 오동나무")],
    [cell("수의"), cell("[샘플] 특 명품수의")],
)


def test_table_and_columns_validate_and_render() -> None:
    body = {
        "type": "doc",
        "content": [
            {
                "type": "columns",
                "content": [
                    {"type": "column", "attrs": {"width": 66}, "content": [SAMPLE_TABLE]},
                    {
                        "type": "column",
                        "attrs": {"width": 34},
                        "content": [para(text("[샘플] 오른쪽"))],
                    },
                ],
            }
        ],
    }
    assert richtext.validate(body) == []
    html = richtext.to_html(body, {})
    assert 'style="grid-template-columns:66fr 34fr"' in html
    assert '<th colspan="2" style="background-color:#d9e2f3">' in html
    assert '<td rowspan="2">' in html
    assert richtext.to_plain(body) == (
        "[샘플] 구분 | 내용\n"
        "[샘플] 고인용품 | 관 | [샘플] 오동나무\n"
        "수의 | [샘플] 특 명품수의\n\n"
        "[샘플] 오른쪽"
    )


def test_rejects_bad_layout_nodes() -> None:
    nested_columns = {
        "type": "doc",
        "content": [
            {
                "type": "columns",
                "content": [
                    {"type": "column", "content": [{"type": "columns", "content": []}]},
                    {"type": "column", "content": [para(text("x"))]},
                ],
            }
        ],
    }
    table_in_cell = {
        "type": "doc",
        "content": [table([{"type": "tableCell", "content": [SAMPLE_TABLE]}])],
    }
    outside_image = {
        "type": "doc",
        "content": [{"type": "image", "attrs": {"src": "https://example.com/a.png"}}],
    }
    bad_span = {"type": "doc", "content": [table([cell("x", colspan=0, background="red;x")])]}
    assert [e.path for e in richtext.validate(nested_columns)] == [
        "content_json.content[0].content[0].content[0]"
    ]
    assert [e.path for e in richtext.validate(table_in_cell)] == [
        "content_json.content[0].content[0].content[0].content[0]"
    ]
    assert [e.path for e in richtext.validate(outside_image)] == [
        "content_json.content[0].attrs.src"
    ]
    assert [e.path for e in richtext.validate(bad_span)] == [
        "content_json.content[0].content[0].content[0].attrs.colspan",
        "content_json.content[0].content[0].content[0].attrs.background",
    ]


def test_upload_and_serve_image(client: TestClient) -> None:
    data = png_bytes()
    res = client.post("/api/assets", content=data, headers={"Content-Type": "image/png"})
    assert res.status_code == 201, res.text
    url = res.json()["url"]
    assert url.startswith("/api/assets/") and url.endswith(".png")
    got = client.get(url)
    assert got.status_code == 200
    assert got.content == data
    assert got.headers["content-type"] == "image/png"

    # 이미지가 아닌 파일, 형식과 내용이 다른 파일은 거절
    res = client.post("/api/assets", content=b"hello", headers={"Content-Type": "text/plain"})
    assert res.status_code == 422
    res = client.post("/api/assets", content=b"not png", headers={"Content-Type": "image/png"})
    assert res.status_code == 422
    assert client.get("/api/assets/../../etc.png").status_code == 404
    assert client.get(f"/api/assets/{uuid.uuid4().hex}.png").status_code == 404


@pytest.mark.skipif(not renderer_available(), reason="Chromium 필요")
def test_publish_document_with_table_columns_and_image(client: TestClient, tmp_path: Path) -> None:
    url = client.post(
        "/api/assets", content=png_bytes(), headers={"Content-Type": "image/png"}
    ).json()["url"]
    body = {
        "type": "doc",
        "content": [
            {
                "type": "columns",
                "content": [
                    {"type": "column", "content": [SAMPLE_TABLE]},
                    {
                        "type": "column",
                        "content": [
                            {"type": "image", "attrs": {"src": url, "width": 120}},
                            para(text("[샘플] 상품 사진")),
                        ],
                    },
                ],
            }
        ],
    }
    module = create_module(client, "kms.layout", body)
    document = create_document(client, title="[샘플] 상품 설명서")
    saved = save(
        client,
        document,
        [
            {
                "id": str(uuid.uuid4()),
                "kind": "MODULE",
                "clause_id": module["id"],
                "clause_revision_no": 1,
            }
        ],
    )
    set_status(client, saved, "ACTIVE")
    preview = client.get(f"/api/documents/{document['id']}/preview").text
    assert f'src="{url}"' in preview

    pub = post(
        client, f"/api/documents/{document['id']}/publications", {"change_reason": "[샘플]"}, 202
    )
    assert render_publication(uuid.UUID(pub["id"])) == DocumentSetStatus.PUBLISHED
    detail = client.get(f"/api/publications/{pub['id']}").json()
    [pdf] = [f for f in detail["files"] if f["format"] == "PDF"]
    path = tmp_path / "out.pdf"
    path.write_bytes(client.get(f"/api/publications/{pub['id']}/files/{pdf['id']}").content)
    reader = PdfReader(path)
    page_text = reader.pages[0].extract_text()
    assert "[샘플] 고인용품" in page_text and "[샘플] 상품 사진" in page_text
    # 이미지가 PDF에 실제로 들어갔는지
    assert len(reader.pages[0].images) == 1
