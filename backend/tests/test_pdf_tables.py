"""PDF에서 표 가져오기. 시험용 PDF는 [샘플] 표 HTML을 렌더러로 만든다. Chromium이 필요하다."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import richtext
from app.rendering.output import render_single
from tests.helpers import renderer_available

pytestmark = pytest.mark.skipif(not renderer_available(), reason="Chromium 필요")

SAMPLE_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
body { font-family: 'Malgun Gothic', 'Noto Sans CJK KR', sans-serif; font-size: 10pt; }
table { border-collapse: collapse; width: 420px; }
td { border: 1px solid #000; padding: 4px; text-align: center; }
.head { background: #8899aa; color: #fff; font-weight: bold; }
.red { color: #e51d24; }
</style></head><body>
<table>
  <tr><td class="head" colspan="2">[샘플] 제공내용</td><td class="head">[샘플] 상품</td></tr>
  <tr><td rowspan="2">고인용품</td><td>관</td><td>[샘플] 오동나무</td></tr>
  <tr><td>수의</td><td><span class="red">★국내최초★</span> 명품수의</td></tr>
  <tr><td>꽃장식</td><td>헌화꽃</td><td>30송이</td></tr>
</table>
</body></html>"""


def _sample_pdf(tmp_path: Path) -> bytes:
    result = render_single(SAMPLE_HTML, stem="sample", footer_label="[샘플]", out_dir=tmp_path)
    return result.files[0].path.read_bytes()


def _cells(table: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return [row["content"] for row in table["content"]]


def _text(cell: dict[str, Any]) -> str:
    return richtext.to_plain({"type": "doc", "content": cell["content"]})


def test_import_ruled_table_with_merges_colors_and_marks(
    client: TestClient, tmp_path: Path
) -> None:
    res = client.post(
        "/api/imports/pdf-tables",
        content=_sample_pdf(tmp_path),
        headers={"Content-Type": "application/pdf"},
    )
    assert res.status_code == 200, res.text
    [found] = res.json()["tables"]
    assert (found["page"], found["rows"], found["cols"]) == (1, 4, 3)
    content = found["content"]
    assert richtext.validate(content) == []
    rows = _cells(content["content"][0])

    head = rows[0][0]
    assert head["attrs"]["colspan"] == 2
    assert head["attrs"]["background"].startswith("#8")  # 화면에 보이는 회청색
    text = head["content"][0]["content"][0]
    assert text["text"] == "[샘플] 제공내용"
    assert {"type": "bold"} in text["marks"]
    assert {"type": "textStyle", "attrs": {"color": "#ffffff"}} in text["marks"]

    merged = rows[1][0]
    assert (_text(merged), merged["attrs"]["rowspan"]) == ("고인용품", 2)
    assert [_text(c) for c in rows[2]] == ["수의", "★국내최초★ 명품수의"]
    red = rows[2][1]["content"][0]["content"][0]
    assert red["text"] == "★국내최초★ "  # 다음 글자와 사이의 공백은 앞 글자에 붙는다
    assert red["marks"] == [{"type": "textStyle", "attrs": {"color": "#e51d24"}}]
    assert rows[2][1]["content"][0]["attrs"] == {"textAlign": "center"}
    assert "<td" in found["preview_html"] and "고인용품" in found["preview_html"]


def test_import_rejects_non_pdf_and_pdf_without_tables(client: TestClient, tmp_path: Path) -> None:
    res = client.post(
        "/api/imports/pdf-tables", content=b"hello", headers={"Content-Type": "application/pdf"}
    )
    assert res.status_code == 422
    no_table = (
        render_single(
            "<!doctype html><meta charset=utf-8><p>[샘플] 표 없는 문서</p>",
            stem="plain",
            footer_label="[샘플]",
            out_dir=tmp_path,
        )
        .files[0]
        .path.read_bytes()
    )
    res = client.post(
        "/api/imports/pdf-tables", content=no_table, headers={"Content-Type": "application/pdf"}
    )
    assert res.status_code == 422
    assert "표를 찾지 못했습니다" in res.json()["errors"][0]["message"]
