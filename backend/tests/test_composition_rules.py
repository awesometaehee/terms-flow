"""조항 조합(A3·A4)·미리보기·발행 요청. 렌더러 없이 실행된다."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.catalog_samples import setup_catalog
from tests.helpers import create_company, create_product, error_paths, set_status


@pytest.fixture
def company_id(client: TestClient) -> str:
    setup_catalog(client)
    return create_company(client)


def _preview(client: TestClient, product: dict[str, Any], **body: Any) -> dict[str, Any]:
    res = client.post(f"/api/products/{product['id']}/preview", json=body)
    assert res.status_code == 200, res.text
    data: dict[str, Any] = res.json()
    return data


def _decisions(preview: dict[str, Any], document_type: str) -> list[tuple[str, bool, int | None]]:
    doc = next(d for d in preview["documents"] if d["document_type"] == document_type)
    return [(c["clause_key"], c["included"], c["order"]) for c in doc["clauses"]]


def test_offline_includes_partner_fee_and_online_excludes_it(
    client: TestClient, company_id: str
) -> None:
    """A3: 협력비 조항은 오프라인만 포함하고 나머지 순서는 유지한다."""
    offline = create_product(client, company_id, channel="OFFLINE", refund_type="REFUND_A")
    online = create_product(
        client, company_id, product_code="P002", channel="ONLINE", refund_type="REFUND_A"
    )

    assert _decisions(_preview(client, offline), "TERMS") == [
        ("terms.purpose", True, 1),
        ("terms.partner_fee", True, 2),
        ("terms.refund_a", True, 3),
        ("terms.refund_b", False, None),
        ("terms.bundle", False, None),
        ("terms.notice", True, 4),
    ]
    online_preview = _preview(client, online)
    assert _decisions(online_preview, "TERMS") == [
        ("terms.purpose", True, 1),
        ("terms.partner_fee", False, None),
        ("terms.refund_a", True, 2),
        ("terms.refund_b", False, None),
        ("terms.bundle", False, None),
        ("terms.notice", True, 3),
    ]
    terms = online_preview["documents"][0]
    reason = next(c["reason"] for c in terms["clauses"] if c["clause_key"] == "terms.partner_fee")
    assert reason == "조건 불일치: 판매 채널 OFFLINE 아님 (현재 ONLINE)"
    assert "협력비 조항" not in terms["html"]


def test_refund_and_bundle_conditions_change_only_their_blocks(
    client: TestClient, company_id: str
) -> None:
    """A4: 환급 방식·결합 상품 조건이 해당 조항과 설명서 템플릿만 바꾼다."""
    standard = create_product(client, company_id, refund_type="REFUND_A")
    bundle = create_product(
        client, company_id, product_code="P002", refund_type="REFUND_B", bundle_type="BUNDLE"
    )

    standard_preview = _preview(client, standard)
    bundle_preview = _preview(client, bundle)

    included = [k for k, inc, _ in _decisions(bundle_preview, "TERMS") if inc]
    assert included == [
        "terms.purpose",
        "terms.partner_fee",
        "terms.refund_b",
        "terms.bundle",
        "terms.notice",
    ]
    descriptions = {
        p["documents"][2]["template_key"]: p["documents"][2]
        for p in (standard_preview, bundle_preview)
    }
    assert set(descriptions) == {"description.standard", "description.bundle"}
    assert "결합 안내" in descriptions["description.bundle"]["html"]
    assert "결합 안내" not in descriptions["description.standard"]["html"]


def test_optional_clause_can_be_excluded_but_required_cannot(
    client: TestClient, company_id: str
) -> None:
    product = create_product(client, company_id, refund_type="REFUND_A")

    preview = _preview(client, product, excluded_clause_keys=["terms.notice"])
    notice = next(
        c for c in preview["documents"][0]["clauses"] if c["clause_key"] == "terms.notice"
    )
    assert (notice["included"], notice["reason"]) == (False, "사용자 제외")

    res = client.post(
        f"/api/products/{product['id']}/preview",
        json={"excluded_clause_keys": ["terms.purpose", "unknown.clause"]},
    )
    assert res.status_code == 422
    assert res.json()["code"] == "COMPOSITION_ERROR"
    assert error_paths(res.json()) == ["excluded_clause_keys[0]", "excluded_clause_keys[1]"]


def test_preview_fills_variables_and_escapes_html(client: TestClient, company_id: str) -> None:
    product = create_product(client, company_id, name="<b>[샘플]</b> 상품", refund_type="REFUND_A")
    preview = _preview(client, product)

    terms_html = preview["documents"][0]["html"]
    assert "&lt;b&gt;[샘플]&lt;/b&gt; 상품 약관" in terms_html
    assert "<b>[샘플]</b>" not in terms_html
    # 모듈 본문의 변수는 강조 표시(span.var) 안에 이스케이프된 값으로 들어간다.
    assert '[샘플] <span class="var">&lt;b&gt;[샘플]&lt;/b&gt; 상품</span> 목적 조항' in terms_html
    assert "{{" not in preview["combined_html"]
    assert [d["label"] for d in preview["documents"]] == ["약관", "약관 주요 내용", "상품설명서"]
    assert preview["combined_html"].count('class="document"') == 3


def test_missing_template_is_composition_error(client: TestClient) -> None:
    product = create_product(client, create_company(client))
    res = client.post(f"/api/products/{product['id']}/preview", json={})
    assert res.status_code == 422
    assert res.json()["code"] == "COMPOSITION_ERROR"
    assert error_paths(res.json()) == [
        "templates.TERMS",
        "templates.TERMS_SUMMARY",
        "templates.PRODUCT_DESCRIPTION",
    ]


def test_publish_request_fixes_revisions_in_manifest(client: TestClient, company_id: str) -> None:
    product = create_product(client, company_id, refund_type="REFUND_A")

    res = client.post(
        f"/api/products/{product['id']}/document-sets", json={"change_reason": "[샘플] 최초 발행"}
    )

    assert res.status_code == 202, res.text
    assert (res.json()["version_no"], res.json()["status"]) == (1, "PENDING")
    detail = client.get(f"/api/document-sets/{res.json()['id']}").json()
    documents = detail["manifest"]["documents"]
    assert [d["template_key"] for d in documents] == [
        "terms.standard",
        "summary.standard",
        "description.standard",
    ]
    assert [(c["clause_key"], c["order"], c["revision_no"]) for c in documents[0]["clauses"]] == [
        ("terms.purpose", 1, 1),
        ("terms.partner_fee", 2, 1),
        ("terms.refund_a", 3, 1),
        ("terms.notice", 4, 1),
    ]
    assert [c["clause_key"] for c in documents[0]["excluded_clauses"]] == [
        "terms.refund_b",
        "terms.bundle",
    ]


def test_ended_product_cannot_preview_or_publish(client: TestClient, company_id: str) -> None:
    product = create_product(client, company_id, refund_type="REFUND_A")
    product = set_status(client, set_status(client, product, "ACTIVE"), "ENDED")

    for url, body in (
        (f"/api/products/{product['id']}/preview", {}),
        (f"/api/products/{product['id']}/document-sets", {"change_reason": "[샘플]"}),
    ):
        res = client.post(url, json=body)
        assert res.status_code == 409
        assert res.json()["code"] == "PRODUCT_ENDED"
    assert client.get(f"/api/products/{product['id']}/document-sets").json() == []


def test_template_layout_and_condition_validation(client: TestClient) -> None:
    res = client.post(
        "/api/templates",
        json={
            "template_key": "terms.bad",
            "document_type": "TERMS",
            "name": "[샘플]",
            "layout_definition": {
                "schemaVersion": 1,
                "blocks": [{"type": "heading", "text": "{{ product.unknown }}"}],
            },
            "selection_condition": {"channel": ["SOMEWHERE"], "color": ["RED"]},
        },
    )
    assert res.status_code == 422
    assert error_paths(res.json()) == [
        "layout_definition.blocks[0].text",
        "selection_condition.channel[0]",
        "selection_condition.color",
    ]

    res = client.post(
        "/api/clauses",
        json={
            "clause_key": "terms.bad",
            "document_type": "TERMS",
            "kind": "COMMON",
            "title": "[샘플]",
            "content": "{{ company.ceo }}",
        },
    )
    assert res.status_code == 422
    assert error_paths(res.json()) == ["content"]
