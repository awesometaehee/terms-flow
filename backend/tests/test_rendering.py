"""PDF/PNG 렌더링과 발행 (A1·A2·A7·A10·A12). worker 컨테이너에서 실행한다."""

import hashlib
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.models import DocumentSetStatus
from app.rendering.publisher import render_and_publish
from app.storage import open_object
from tests.catalog_samples import setup_catalog
from tests.helpers import (
    composition,
    create_company,
    create_product,
    renderer_available,
    set_status,
    variant,
)

pytestmark = pytest.mark.skipif(
    not renderer_available(), reason="Chromium 필요: uv run playwright install chromium"
)


@pytest.fixture
def catalog(client: TestClient) -> dict[str, str]:
    return setup_catalog(client)


def _publish(client: TestClient, product: dict[str, Any], reason: str = "[샘플]") -> dict[str, Any]:
    res = client.post(
        f"/api/products/{product['id']}/document-sets", json={"change_reason": reason}
    )
    assert res.status_code == 202, res.text
    status = render_and_publish(uuid.UUID(res.json()["id"]))
    detail: dict[str, Any] = client.get(f"/api/document-sets/{res.json()['id']}").json()
    assert status == DocumentSetStatus.PUBLISHED, detail["failure_reason"]
    return detail


def _files(detail: dict[str, Any], document_type: str, fmt: str) -> list[dict[str, Any]]:
    return [
        f for f in detail["files"] if f["document_type"] == document_type and f["format"] == fmt
    ]


def _download(client: TestClient, detail: dict[str, Any], file: dict[str, Any], to: Path) -> Path:
    res = client.get(f"/api/document-sets/{detail['id']}/files/{file['id']}")
    assert res.status_code == 200
    assert hashlib.sha256(res.content).hexdigest() == file["sha256"]
    path = to / str(file["file_name"])
    path.write_bytes(res.content)
    return path


def _page_texts(pdf: Path) -> list[str]:
    return [page.extract_text() for page in PdfReader(pdf).pages]


def test_publish_creates_individual_and_combined_pdf_png(
    client: TestClient, catalog: dict[str, str], tmp_path: Path
) -> None:
    """A1·A12: 3종 개별 PDF/PNG와 통합본. 통합본은 약관→주요 내용→설명서 순서다."""
    product = create_product(client, create_company(client), refund_type="REFUND_A")
    detail = _publish(client, product)

    assert detail["status"] == "PUBLISHED"
    assert detail["manifest"]["renderer_version"].startswith("terms-flow-renderer/4; chromium/")
    page_counts = {}
    for doc_type, label in (
        ("TERMS", "약관"),
        ("TERMS_SUMMARY", "약관주요내용"),
        ("PRODUCT_DESCRIPTION", "상품설명서"),
    ):
        [pdf] = _files(detail, doc_type, "PDF")
        assert pdf["file_name"] == f"P001_v1_{label}.pdf"
        pages = len(PdfReader(_download(client, detail, pdf, tmp_path)).pages)
        pngs = _files(detail, doc_type, "PNG")
        assert [p["page_no"] for p in pngs] == list(range(1, pages + 1))
        assert pngs[0]["file_name"] == f"P001_v1_{label}_p01.png"
        page_counts[doc_type] = pages

    [combined] = _files(detail, "COMBINED", "PDF")
    combined_texts = _page_texts(_download(client, detail, combined, tmp_path))
    assert len(combined_texts) == sum(page_counts.values())
    assert len(_files(detail, "COMBINED", "PNG")) == len(combined_texts)
    full = "\n".join(combined_texts)
    positions = [full.index(t) for t in ("약관\n", "약관 주요 내용", "상품설명서")]
    assert positions == sorted(positions)
    # 한글 텍스트가 PDF에 텍스트로 들어가 있다.
    assert "[샘플] 환급 방식 A 조항" in full
    assert "제2조 (협력비)" in full

    # 매니페스트 파일 목록과 DB 파일 행이 같다.
    manifest_hashes = {
        (f["storage_key"].rsplit("/", 1)[1], f["sha256"]) for f in detail["manifest"]["files"]
    }
    assert manifest_hashes == {(f["file_name"], f["sha256"]) for f in detail["files"]}
    assert (
        client.get(f"/api/products/{product['id']}").json()["latest_document_set_version_no"] == 1
    )


def test_png_pages_match_pdf_pages(
    client: TestClient, catalog: dict[str, str], tmp_path: Path
) -> None:
    product = create_product(client, create_company(client), refund_type="REFUND_A")
    detail = _publish(client, product)
    [png] = [f for f in _files(detail, "TERMS", "PNG") if f["page_no"] == 1]
    path = _download(client, detail, png, tmp_path)
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    # 150dpi A4 → 약 1240 x 1754 픽셀
    width = int.from_bytes(path.read_bytes()[16:20], "big")
    assert 1200 <= width <= 1280


def test_long_table_with_multiple_variants_spans_pages_without_loss(
    client: TestClient, catalog: dict[str, str], tmp_path: Path
) -> None:
    """A2·A10: 구성 4개 × 품목 60개. 행이 잘리거나 순서가 바뀌지 않고 머리글이 매 쪽 반복된다."""
    items = [
        {
            "id": f"item_{i:02d}",
            "label": f"[샘플] 품목 {i:02d}",
            "specification": "[샘플] 긴 규격 설명 " * 3,
            "quantity": {"value": i, "unit": "개"},
            "notes": ["[샘플] 추가 비용 조건 확인"] if i % 7 == 0 else [],
            "order": i,
        }
        for i in range(1, 61)
    ]
    long_comp = composition(
        groups=[{"id": "goods", "label": "[샘플] 품목 그룹", "order": 10, "items": items}]
    )
    variants = [variant(f"V{n}", n * 1_000_000, n, composition=long_comp) for n in range(1, 5)]
    product = create_product(
        client, create_company(client), variants=variants, refund_type="REFUND_A"
    )

    detail = _publish(client, product)

    [pdf] = _files(detail, "PRODUCT_DESCRIPTION", "PDF")
    texts = _page_texts(_download(client, detail, pdf, tmp_path))
    assert len(texts) >= 3
    full = "\n".join(texts)
    positions = [full.index(f"[샘플] 품목 {i:02d}") for i in range(1, 61)]
    assert positions == sorted(positions)
    # 표 행이 있는 모든 쪽에 표 머리글(마지막 구성 열 이름)이 반복된다.
    for page_text in texts:
        if "[샘플] 품목 " in page_text:
            assert "[샘플] V4 (4,000,000원)" in " ".join(page_text.split())
    assert len(_files(detail, "PRODUCT_DESCRIPTION", "PNG")) == len(texts)


def test_past_version_is_unchanged_after_clause_revision(
    client: TestClient, catalog: dict[str, str], tmp_path: Path
) -> None:
    """A7: 조항이 바뀐 뒤에도 이전 버전의 manifest·HTML·파일은 발행 당시와 같다."""
    product = create_product(client, create_company(client), refund_type="REFUND_A")
    v1 = _publish(client, product, "[샘플] 최초 발행")
    v1_terms_pdf = _download(client, v1, _files(v1, "TERMS", "PDF")[0], tmp_path)

    res = client.post(
        f"/api/clauses/{catalog['terms.purpose']}/revisions",
        json={
            "base_revision_no": 1,
            "content": "[샘플] 개정된 목적 조항",
            "change_reason": "[샘플]",
        },
    )
    assert res.status_code == 201
    v2 = _publish(client, product, "[샘플] 공통 문구 수정")

    v1_again = client.get(f"/api/document-sets/{v1['id']}").json()
    assert v1_again == v1
    v1_html = client.get(f"/api/document-sets/{v1['id']}/html").text
    assert "[샘플] P001 목적 조항" not in v1_html  # 변수는 상품명으로 채워진다
    assert '[샘플] <span class="var">[샘플] 상품</span> 목적 조항' in v1_html
    assert "개정된 목적 조항" not in v1_html
    assert "개정된 목적 조항" in client.get(f"/api/document-sets/{v2['id']}/html").text

    v2_text = "\n".join(_page_texts(_download(client, v2, _files(v2, "TERMS", "PDF")[0], tmp_path)))
    assert "[샘플] 개정된 목적 조항" in v2_text
    v1_text = "\n".join(_page_texts(v1_terms_pdf))
    assert "개정된" not in v1_text
    purpose = [
        c for c in v2["manifest"]["documents"][0]["clauses"] if c["clause_key"] == "terms.purpose"
    ]
    assert purpose[0]["revision_no"] == 2
    for f in v1["manifest"]["files"]:
        body = open_object(f["storage_key"]).read()
        assert hashlib.sha256(body).hexdigest() == f["sha256"]


def test_product_ended_before_rendering_is_not_published(
    client: TestClient, catalog: dict[str, str]
) -> None:
    product = create_product(client, create_company(client), refund_type="REFUND_A")
    product = set_status(client, product, "ACTIVE")
    res = client.post(
        f"/api/products/{product['id']}/document-sets", json={"change_reason": "[샘플]"}
    )
    set_status(client, product, "ENDED")

    assert render_and_publish(uuid.UUID(res.json()["id"])) == DocumentSetStatus.FAILED
    detail = client.get(f"/api/document-sets/{res.json()['id']}").json()
    assert detail["failure_reason"].startswith("판매 종료")
    assert detail["files"] == []


def test_rendering_twice_is_idempotent(client: TestClient, catalog: dict[str, str]) -> None:
    product = create_product(client, create_company(client), refund_type="REFUND_A")
    detail = _publish(client, product)
    assert render_and_publish(uuid.UUID(detail["id"])) == DocumentSetStatus.PUBLISHED
    assert client.get(f"/api/document-sets/{detail['id']}").json() == detail
