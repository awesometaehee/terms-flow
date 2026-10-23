"""공통 조항 일괄 수정 (A5·A6·A8·A11). 렌더링이 필요하므로 worker 컨테이너에서 실행한다."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models import DocumentSetStatus
from app.rendering import publisher
from app.rendering.output import render_outputs as real_render
from app.rendering.publisher import render_and_publish
from tests.catalog_samples import setup_catalog
from tests.helpers import create_company, create_product, renderer_available, set_status

pytestmark = pytest.mark.skipif(
    not renderer_available(), reason="Chromium 필요: uv run playwright install chromium"
)


@pytest.fixture
def catalog(client: TestClient) -> dict[str, str]:
    return setup_catalog(client)


def _published_product(
    client: TestClient, company_id: str, code: str, **changes: Any
) -> dict[str, Any]:
    """ACTIVE 상품을 만들고 v1을 발행한다."""
    product = create_product(
        client, company_id, product_code=code, refund_type="REFUND_A", **changes
    )
    product = set_status(client, product, "ACTIVE")
    res = client.post(
        f"/api/products/{product['id']}/document-sets", json={"change_reason": "[샘플]"}
    )
    assert res.status_code == 202, res.text
    assert render_and_publish(uuid.UUID(res.json()["id"])) == DocumentSetStatus.PUBLISHED
    detail: dict[str, Any] = client.get(f"/api/products/{product['id']}").json()
    return detail


def _new_revision(client: TestClient, clause_id: str, base: int = 1) -> int:
    res = client.post(
        f"/api/clauses/{clause_id}/revisions",
        json={
            "base_revision_no": base,
            "content": f"[샘플] 개정 목적 조항 {base + 1}",
            "change_reason": "[샘플]",
        },
    )
    assert res.status_code == 201, res.text
    revision_no: int = res.json()["revision_no"]
    return revision_no


def _versions(client: TestClient, product: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = client.get(f"/api/products/{product['id']}/document-sets").json()
    return rows


def _run_job(
    client: TestClient, clause_id: str, revision_no: int, request_id: str
) -> dict[str, Any]:
    res = client.post(
        "/api/bulk-updates",
        json={
            "request_id": request_id,
            "clause_id": clause_id,
            "revision_no": revision_no,
            "change_reason": "[샘플] 공통 문구 수정",
        },
    )
    assert res.status_code == 202, res.text
    job: dict[str, Any] = res.json()
    return job


def _render_job(client: TestClient, job: dict[str, Any]) -> dict[str, Any]:
    """worker 대신 작업에 속한 PENDING 버전을 렌더링한다."""
    for item in job["items"]:
        if item["result"] == "RUNNING":
            render_and_publish(uuid.UUID(item["version_id"]))
    detail: dict[str, Any] = client.get(f"/api/bulk-updates/{job['id']}").json()
    return detail


def test_bulk_update_applies_only_to_active_products(
    client: TestClient, catalog: dict[str, str]
) -> None:
    """A5·A11: 활성 2개만 새 버전. 종료 1개는 데이터·버전·파일 해시가 그대로다."""
    company_id = create_company(client)
    active_a = _published_product(client, company_id, "ACT-A")
    active_b = _published_product(client, company_id, "ACT-B")
    ended = _published_product(client, company_id, "END-C")
    ended = set_status(client, ended, "ENDED")
    draft = create_product(client, company_id, product_code="DRF-D", refund_type="REFUND_A")
    ended_before = {
        "product": client.get(f"/api/products/{ended['id']}").json(),
        "versions": _versions(client, ended),
        "detail": client.get(f"/api/document-sets/{_versions(client, ended)[0]['id']}").json(),
    }

    revision_no = _new_revision(client, catalog["terms.purpose"])
    impact = client.post(
        "/api/bulk-updates/preview",
        json={"clause_id": catalog["terms.purpose"], "revision_no": revision_no},
    ).json()
    assert [t["product_code"] for t in impact["targets"]] == ["ACT-A", "ACT-B"]
    assert {e["product_code"]: e["status"] for e in impact["excluded"]} == {
        "DRF-D": "DRAFT",
        "END-C": "ENDED",
    }
    assert impact["previous_revision"]["content"] == "[샘플] {{ product.name }} 목적 조항"
    assert impact["revision"]["content"] == "[샘플] 개정 목적 조항 2"
    assert impact["targets"][0]["current_clause_revision_no"] == 1

    job = _render_job(
        client, _run_job(client, catalog["terms.purpose"], revision_no, "req-a5-0001")
    )

    assert job["counts"] == {"total": 2, "running": 0, "succeeded": 2, "failed": 0, "skipped": 0}
    assert job["finished"] is True
    for product in (active_a, active_b):
        versions = _versions(client, product)
        assert [(v["version_no"], v["status"]) for v in versions] == [
            (2, "PUBLISHED"),
            (1, "PUBLISHED"),
        ]
        assert versions[0]["batch_id"] == job["id"]
        html = client.get(f"/api/document-sets/{versions[0]['id']}/html").text
        assert "[샘플] 개정 목적 조항 2" in html
    assert client.get(f"/api/products/{ended['id']}").json() == ended_before["product"]
    assert _versions(client, ended) == ended_before["versions"]
    assert (
        client.get(f"/api/document-sets/{ended_before['versions'][0]['id']}").json()
        == ended_before["detail"]
    )
    assert _versions(client, draft) == []

    # 다시 영향 분석하면 활성 상품은 이미 반영됨으로 제외된다.
    again = client.post(
        "/api/bulk-updates/preview",
        json={"clause_id": catalog["terms.purpose"], "revision_no": revision_no},
    ).json()
    assert again["targets"] == []
    assert sorted(e["product_code"] for e in again["excluded"]) == [
        "ACT-A",
        "ACT-B",
        "DRF-D",
        "END-C",
    ]


def test_product_ended_during_bulk_update_is_skipped(
    client: TestClient, catalog: dict[str, str]
) -> None:
    """A6: 버전 생성 뒤 렌더링 전에 종료된 상품은 발행하지 않고 건너뜀으로 기록한다."""
    company_id = create_company(client)
    keep = _published_product(client, company_id, "KEEP")
    stop = _published_product(client, company_id, "STOP")
    revision_no = _new_revision(client, catalog["terms.purpose"])

    job = _run_job(client, catalog["terms.purpose"], revision_no, "req-a6-0001")
    set_status(client, client.get(f"/api/products/{stop['id']}").json(), "ENDED")
    job = _render_job(client, job)

    results = {i["code"]: (i["result"], i["message"]) for i in job["items"]}
    assert results["KEEP"] == ("SUCCEEDED", None)
    assert results["STOP"][0] == "SKIPPED"
    assert "판매 종료" in results["STOP"][1]
    assert job["counts"]["skipped"] == 1
    assert [v["status"] for v in _versions(client, stop)] == ["FAILED", "PUBLISHED"]
    assert client.get(f"/api/products/{keep['id']}").json()["latest_document_set_version_no"] == 2


def test_failed_render_is_isolated_and_retried_without_duplicates(
    client: TestClient, catalog: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A8: 일부 렌더링 실패 → 기존 발행본 유지, 실패 대상만 재시도, 중복 버전 없음."""
    company_id = create_company(client)
    ok = _published_product(client, company_id, "OK-1")
    bad = _published_product(client, company_id, "BAD-1")
    revision_no = _new_revision(client, catalog["terms.purpose"])

    def flaky_render(plan: Any, **kwargs: Any) -> Any:
        if plan.snapshot["product"]["product_code"] == "BAD-1":
            raise RuntimeError("[샘플] 렌더링 오류")
        return real_render(plan, **kwargs)

    monkeypatch.setattr(publisher, "render_outputs", flaky_render)
    job = _render_job(
        client, _run_job(client, catalog["terms.purpose"], revision_no, "req-a8-0001")
    )
    results = {i["code"]: i for i in job["items"]}
    assert results["OK-1"]["result"] == "SUCCEEDED"
    assert results["BAD-1"]["result"] == "FAILED"
    assert "[샘플] 렌더링 오류" in results["BAD-1"]["message"]
    assert client.get(f"/api/products/{bad['id']}").json()["latest_document_set_version_no"] == 1

    # 같은 요청 ID로 다시 보내도 새 작업·버전이 생기지 않는다.
    same = _run_job(client, catalog["terms.purpose"], revision_no, "req-a8-0001")
    assert same["id"] == job["id"]
    ok_versions = _versions(client, ok)

    monkeypatch.setattr(publisher, "render_outputs", real_render)
    res = client.post(f"/api/bulk-updates/{job['id']}/retry")
    assert res.status_code == 200
    retried = _render_job(client, res.json())

    assert retried["counts"]["succeeded"] == 2
    assert [(v["version_no"], v["status"]) for v in _versions(client, bad)] == [
        (2, "PUBLISHED"),
        (1, "PUBLISHED"),
    ]
    assert _versions(client, ok) == ok_versions
    # 재시도를 또 해도 처리할 실패가 없으므로 변화가 없다.
    res = client.post(f"/api/bulk-updates/{job['id']}/retry")
    assert res.json()["counts"] == retried["counts"]
    assert len(_versions(client, bad)) == 2


def test_bulk_update_requires_latest_revision(client: TestClient, catalog: dict[str, str]) -> None:
    second = _new_revision(client, catalog["terms.purpose"])
    _new_revision(client, catalog["terms.purpose"], base=second)
    res = client.post(
        "/api/bulk-updates/preview",
        json={"clause_id": catalog["terms.purpose"], "revision_no": second},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "VERSION_CONFLICT"


def test_bulk_update_keeps_user_excluded_optional_clause(
    client: TestClient, catalog: dict[str, str]
) -> None:
    company_id = create_company(client)
    product = create_product(client, company_id, product_code="OPT", refund_type="REFUND_A")
    product = set_status(client, product, "ACTIVE")
    res = client.post(
        f"/api/products/{product['id']}/document-sets",
        json={"change_reason": "[샘플]", "excluded_clause_keys": ["terms.notice"]},
    )
    render_and_publish(uuid.UUID(res.json()["id"]))

    revision_no = _new_revision(client, catalog["terms.purpose"])
    _render_job(client, _run_job(client, catalog["terms.purpose"], revision_no, "req-opt-0001"))

    latest = _versions(client, product)[0]
    manifest = client.get(f"/api/document-sets/{latest['id']}").json()["manifest"]
    excluded = {c["clause_key"]: c["reason"] for c in manifest["documents"][0]["excluded_clauses"]}
    assert excluded["terms.notice"] == "사용자 제외"
