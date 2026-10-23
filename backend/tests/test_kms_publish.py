"""KMS 문서 발행(PDF·PNG)과 공통 모듈 일괄 반영. Chromium이 필요하다."""

import hashlib
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.models import DocumentSetStatus
from app.rendering.publisher import render_publication
from tests.helpers import renderer_available
from tests.kms_helpers import (
    create_document,
    create_module,
    create_variable,
    doc,
    module_block,
    post,
    save,
    set_status,
    text,
    var,
)

pytestmark = pytest.mark.skipif(
    not renderer_available(), reason="Chromium 필요: uv run playwright install chromium"
)


@pytest.fixture
def module(client: TestClient) -> dict[str, Any]:
    create_variable(client, "service_name", "서비스명")
    return create_module(
        client,
        "kms.purpose",
        doc([text("[샘플] 본 약관은 "), var("service_name"), text(" 이용 조건을 정한다.", "bold")]),
    )


def _publish(
    client: TestClient, document: dict[str, Any], reason: str = "[샘플]"
) -> dict[str, Any]:
    pub = post(
        client, f"/api/documents/{document['id']}/publications", {"change_reason": reason}, 202
    )
    assert render_publication(uuid.UUID(pub["id"])) == DocumentSetStatus.PUBLISHED
    detail: dict[str, Any] = client.get(f"/api/publications/{pub['id']}").json()
    return detail


def _pdf_text(client: TestClient, publication: dict[str, Any], tmp_path: Path) -> str:
    [pdf] = [f for f in publication["files"] if f["format"] == "PDF"]
    res = client.get(f"/api/publications/{publication['id']}/files/{pdf['id']}")
    assert hashlib.sha256(res.content).hexdigest() == pdf["sha256"]
    path = tmp_path / pdf["file_name"]
    path.write_bytes(res.content)
    return "\n".join(p.extract_text() for p in PdfReader(path).pages)


def _active_document(
    client: TestClient, module: dict[str, Any], title: str, block: dict[str, Any] | None = None
) -> dict[str, Any]:
    document = create_document(client, title=title)
    saved = save(
        client,
        document,
        [block or module_block(module)],
        variable_values={"service_name": "[샘플]서비스"},
    )
    return set_status(client, saved, "ACTIVE")


def test_publish_document_to_pdf_and_png(
    client: TestClient, module: dict[str, Any], tmp_path: Path
) -> None:
    document = _active_document(client, module, "[샘플] 이용 약관")
    publication = _publish(client, document)

    assert publication["status"] == "PUBLISHED"
    assert publication["revision_no"] == 2
    formats = sorted((f["format"], f["page_no"]) for f in publication["files"])
    assert formats == [("PDF", None), ("PNG", 1)]
    assert [f["file_name"] for f in publication["files"]][0].startswith("[샘플]_이용_약관_v1")
    pdf_text = _pdf_text(client, publication, tmp_path)
    assert "[샘플] 이용 약관" in pdf_text
    assert "[샘플]서비스" in pdf_text
    assert client.get(f"/api/documents/{document['id']}").json()["latest_publication_no"] == 1


def test_bulk_update_reaches_only_active_unmodified_documents(
    client: TestClient, module: dict[str, Any], tmp_path: Path
) -> None:
    active = _active_document(client, module, "[샘플] 사용 중 문서")
    _publish(client, active)
    modified = _active_document(
        client,
        module,
        "[샘플] 수정한 문서",
        module_block(module, doc([text("[샘플] 문서에서 고친 문구 "), var("service_name")])),
    )
    draft = create_document(client, title="[샘플] 작성 중 문서")
    save(client, draft, [module_block(module)], variable_values={"service_name": "x"})
    ended = set_status(client, _active_document(client, module, "[샘플] 종료 문서"), "ENDED")
    ended_revisions = client.get(f"/api/documents/{ended['id']}/revisions").json()

    revision = post(
        client,
        f"/api/clauses/{module['id']}/revisions",
        {
            "base_revision_no": 1,
            "content_json": doc([text("[샘플] 개정된 목적 "), var("service_name")]),
            "change_reason": "[샘플] 개정",
        },
    )
    impact = post(
        client,
        "/api/bulk-updates/preview",
        {"clause_id": module["id"], "revision_no": revision["revision_no"]},
        status=200,
    )
    assert [d["title"] for d in impact["document_targets"]] == ["[샘플] 사용 중 문서"]
    reasons = {d["title"]: d["reason"] for d in impact["document_excluded"]}
    assert set(reasons) == {"[샘플] 수정한 문서", "[샘플] 작성 중 문서", "[샘플] 종료 문서"}
    assert "고친 단락" in reasons["[샘플] 수정한 문서"]

    job = post(
        client,
        "/api/bulk-updates",
        {
            "request_id": "req-kms-0001",
            "clause_id": module["id"],
            "revision_no": revision["revision_no"],
            "change_reason": "[샘플] 공통 문구 수정",
        },
        status=202,
    )
    [item] = job["items"]
    assert (item["target_type"], item["name"], item["result"]) == (
        "DOCUMENT",
        "[샘플] 사용 중 문서",
        "RUNNING",
    )
    render_publication(uuid.UUID(item["version_id"]))
    job = client.get(f"/api/bulk-updates/{job['id']}").json()
    assert job["counts"]["succeeded"] == 1

    detail = client.get(f"/api/documents/{active['id']}").json()
    assert detail["blocks"][0]["clause_revision_no"] == 2
    assert detail["latest_publication_no"] == 2
    publication = client.get(f"/api/publications/{item['version_id']}").json()
    assert publication["batch_id"] == job["id"]
    assert "[샘플] 개정된 목적" in _pdf_text(client, publication, tmp_path)

    # 제외된 문서는 그대로
    assert (
        client.get(f"/api/documents/{modified['id']}").json()["blocks"][0]["clause_revision_no"]
        == 1
    )
    assert client.get(f"/api/documents/{draft['id']}").json()["blocks"][0]["outdated"] is True
    assert client.get(f"/api/documents/{ended['id']}/revisions").json() == ended_revisions


def _add_variable_to_module(client: TestClient, module: dict[str, Any]) -> dict[str, Any]:
    create_variable(client, "new_var", "[샘플] 새 변수")
    return post(
        client,
        f"/api/clauses/{module['id']}/revisions",
        {
            "base_revision_no": 1,
            "content_json": doc([text("[샘플] 개정 "), var("service_name"), var("new_var")]),
            "change_reason": "[샘플] 개정",
        },
    )


def _run(client: TestClient, module: dict[str, Any], request_id: str, **extra: Any) -> Any:
    return post(
        client,
        "/api/bulk-updates",
        {
            "request_id": request_id,
            "clause_id": module["id"],
            "revision_no": 2,
            "change_reason": "[샘플] 변수 추가",
            **extra,
        },
        status=202,
    )


def test_bulk_update_fills_new_variable_value(client: TestClient, module: dict[str, Any]) -> None:
    active = _active_document(client, module, "[샘플] 사용 중 문서")
    _add_variable_to_module(client, module)
    impact = post(
        client, "/api/bulk-updates/preview", {"clause_id": module["id"], "revision_no": 2}, 200
    )
    assert impact["missing_variables"] == [
        {"key": "new_var", "label": "[샘플] 새 변수", "documents": 1}
    ]

    job = _run(client, module, "req-kms-fill-var", variable_values={"new_var": "[샘플]값"})
    [item] = job["items"]
    assert item["result"] == "RUNNING"
    assert render_publication(uuid.UUID(item["version_id"])) == DocumentSetStatus.PUBLISHED
    detail = client.get(f"/api/documents/{active['id']}").json()
    assert detail["variable_values"] == {"service_name": "[샘플]서비스", "new_var": "[샘플]값"}


def test_bulk_update_without_value_applies_content_and_retries_with_value(
    client: TestClient, module: dict[str, Any]
) -> None:
    active = _active_document(client, module, "[샘플] 사용 중 문서")
    _add_variable_to_module(client, module)
    job = _run(client, module, "req-kms-missing-var")
    [item] = job["items"]
    assert item["result"] == "FAILED"
    assert "본문은 반영" in item["message"]
    assert [m["key"] for m in job["missing_variables"]] == ["new_var"]
    detail = client.get(f"/api/documents/{active['id']}").json()
    assert detail["blocks"][0]["clause_revision_no"] == 2

    # 결과 화면에서 값을 넣어 다시 시도하면 값을 저장하고 발행만 한다
    job = post(
        client,
        f"/api/bulk-updates/{job['id']}/retry",
        {"variable_values": {"new_var": "[샘플]값"}},
        status=200,
    )
    [item] = job["items"]
    assert item["result"] == "RUNNING"
    assert job["missing_variables"] == []
    assert render_publication(uuid.UUID(item["version_id"])) == DocumentSetStatus.PUBLISHED
    assert client.get(f"/api/documents/{active['id']}").json()["variable_values"]["new_var"] == (
        "[샘플]값"
    )


def test_variable_value_bulk_update(client: TestClient, module: dict[str, Any]) -> None:
    create_variable(client, "fee", "[샘플] 수수료", default="1,000원")
    variable = next(v for v in client.get("/api/variables").json() if v["key"] == "fee")
    fee_module = create_module(client, "kms.fee", doc([text("[샘플] 수수료 "), var("fee")]))

    def fee_document(title: str, values: dict[str, str]) -> dict[str, Any]:
        document = create_document(client, title=title)
        saved = save(client, document, [module_block(fee_module)], variable_values=values)
        return set_status(client, saved, "ACTIVE")

    default_doc = fee_document("[샘플] 기본값 문서", {})
    own_a = fee_document("[샘플] 직접 입력 A", {"fee": "500원"})
    own_b = fee_document("[샘플] 직접 입력 B", {"fee": "700원"})
    draft = create_document(client, title="[샘플] 작성 중")
    save(client, draft, [module_block(fee_module)])
    unrelated = _active_document(client, module, "[샘플] 다른 문서")

    res = client.patch(f"/api/variables/{variable['id']}", json={"default_value": "2,000원"})
    assert res.status_code == 200, res.text
    impact = post(client, f"/api/variables/{variable['id']}/bulk-updates/preview", {}, 200)
    assert [d["title"] for d in impact["document_targets"]] == ["[샘플] 기본값 문서"]
    assert [(d["title"], d["own_value"]) for d in impact["own_value_documents"]] == [
        ("[샘플] 직접 입력 A", "500원"),
        ("[샘플] 직접 입력 B", "700원"),
    ]
    assert [d["title"] for d in impact["document_excluded"]] == ["[샘플] 작성 중"]

    job = post(
        client,
        f"/api/variables/{variable['id']}/bulk-updates",
        {"request_id": "req-var-0001", "overwrite_document_ids": [own_a["id"]]},
        202,
    )
    assert (job["kind"], job["variable_label"], job["variable_value"]) == (
        "VARIABLE",
        "[샘플] 수수료",
        "2,000원",
    )
    assert sorted(i["name"] for i in job["items"]) == ["[샘플] 기본값 문서", "[샘플] 직접 입력 A"]
    assert {d["title"] for d in job["document_excluded"]} == {
        "[샘플] 직접 입력 B",
        "[샘플] 작성 중",
    }
    for item in job["items"]:
        assert render_publication(uuid.UUID(item["version_id"])) == DocumentSetStatus.PUBLISHED
        assert "2,000원" in client.get(f"/api/documents/{item['target_id']}/preview").text

    assert client.get(f"/api/documents/{own_a['id']}").json()["variable_values"] == {}
    assert client.get(f"/api/documents/{own_b['id']}").json()["variable_values"] == {"fee": "700원"}
    assert client.get(f"/api/documents/{default_doc['id']}").json()["latest_publication_no"] == 1
    assert client.get(f"/api/documents/{unrelated['id']}").json()["latest_publication_no"] is None

    # 다시 미리보면 반영한 문서는 '이미 이 값'으로 빠진다
    impact = post(client, f"/api/variables/{variable['id']}/bulk-updates/preview", {}, 200)
    assert impact["document_targets"] == []
