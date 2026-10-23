from fastapi.testclient import TestClient

from tests.helpers import (
    composition,
    create_company,
    create_product,
    error_paths,
    product_payload,
    set_status,
    variant,
)


def test_create_single_variant_product(client: TestClient) -> None:
    company_id = create_company(client)
    product = create_product(client, company_id)

    assert product["status"] == "DRAFT"
    assert product["lock_version"] == 1
    assert product["current_revision_no"] == 1
    assert product["latest_document_set_version_no"] is None
    assert [v["variant_code"] for v in product["variants"]] == ["V1"]
    assert product["variants"][0]["composition"] == composition()


def test_create_multiple_variants_keeps_each_composition(client: TestClient) -> None:
    """A2: 한 상품에 금액대 3개, 서로 다른 품목."""
    company_id = create_company(client)
    small = composition(groups=[])
    variants = [
        variant("V300", 3_000_000, 30),
        variant("V100", 1_000_000, 10, composition=small),
        variant("V200", 2_000_000, 20),
    ]
    product = create_product(client, company_id, variants=variants)

    got = product["variants"]
    assert [v["variant_code"] for v in got] == ["V100", "V200", "V300"]
    assert [v["price_amount"] for v in got] == [1_000_000, 2_000_000, 3_000_000]
    assert got[0]["composition"] == small
    assert got[1]["composition"] == composition()

    snapshot = client.get(f"/api/products/{product['id']}/revisions/1").json()["snapshot"]
    assert [v["variant_code"] for v in snapshot["variants"]] == ["V100", "V200", "V300"]
    assert snapshot["product"]["company"]["code"] == "SAMPLE-CO"


def test_invalid_composition_reports_field_paths(client: TestClient) -> None:
    """A9: 필수명 누락, 중복 ID, 잘못된 수량."""
    company_id = create_company(client)
    bad = composition()
    items = bad["groups"][0]["items"]
    items[0]["label"] = " "
    items[1]["quantity"] = {"value": -1, "unit": "벌"}
    duplicated = composition()
    duplicated["groups"][0]["items"][1]["id"] = "coffin"
    payload = product_payload(
        company_id,
        variants=[
            variant("V1", 1_000_000, 10),
            variant("V2", 2_000_000, 20, composition=bad),
            variant("V3", 3_000_000, 30, composition=duplicated),
        ],
    )

    res = client.post("/api/products", json=payload)

    assert res.status_code == 422
    assert res.json()["code"] == "VALIDATION_ERROR"
    assert error_paths(res.json()) == [
        "variants[1].composition.groups[0].items[0].label",
        "variants[1].composition.groups[0].items[1].quantity",
        "variants[2].composition.groups[0].items[1].id",
    ]
    assert client.get("/api/products").json() == []


def test_request_shape_errors_use_body_paths(client: TestClient) -> None:
    company_id = create_company(client)
    payload = product_payload(company_id)
    del payload["variants"][0]["price_amount"]
    payload["unknown_field"] = 1

    res = client.post("/api/products", json=payload)

    assert res.status_code == 422
    assert sorted(error_paths(res.json())) == ["unknown_field", "variants[0].price_amount"]


def test_duplicate_variant_code_and_unknown_company(client: TestClient) -> None:
    company_id = create_company(client)
    payload = product_payload(
        company_id, variants=[variant("V1", 1_000_000, 10), variant("V1", 2_000_000, 20)]
    )
    res = client.post("/api/products", json=payload)
    assert res.status_code == 422
    assert error_paths(res.json()) == ["variants[1].variant_code"]

    payload = product_payload("00000000-0000-0000-0000-000000000000")
    res = client.post("/api/products", json=payload)
    assert res.status_code == 422
    assert error_paths(res.json()) == ["company_id"]


def test_duplicate_product_code_is_conflict(client: TestClient) -> None:
    company_id = create_company(client)
    create_product(client, company_id)
    res = client.post("/api/products", json=product_payload(company_id))
    assert res.status_code == 409
    assert res.json()["code"] == "DUPLICATE_PRODUCT_CODE"


def test_update_creates_new_revision_and_keeps_old_snapshot(client: TestClient) -> None:
    company_id = create_company(client)
    product = create_product(client, company_id)

    res = client.patch(
        f"/api/products/{product['id']}",
        json={
            "lock_version": product["lock_version"],
            "change_reason": "[샘플] 금액대 추가",
            "name": "[샘플] 상품 변경",
            "variants": [variant("V1", 3_500_000, 10), variant("V2", 5_000_000, 20)],
        },
    )

    assert res.status_code == 200, res.text
    updated = res.json()
    assert updated["lock_version"] == 2
    assert updated["current_revision_no"] == 2
    assert updated["name"] == "[샘플] 상품 변경"
    assert [(v["variant_code"], v["price_amount"]) for v in updated["variants"]] == [
        ("V1", 3_500_000),
        ("V2", 5_000_000),
    ]
    first = client.get(f"/api/products/{product['id']}/revisions/1").json()
    assert first["snapshot"]["product"]["name"] == "[샘플] 상품"
    assert [v["price_amount"] for v in first["snapshot"]["variants"]] == [3_000_000]
    revisions = client.get(f"/api/products/{product['id']}/revisions").json()
    assert [r["change_reason"] for r in revisions] == ["최초 등록", "[샘플] 금액대 추가"]


def test_variant_only_update_bumps_lock_version(client: TestClient) -> None:
    company_id = create_company(client)
    product = create_product(client, company_id)
    res = client.patch(
        f"/api/products/{product['id']}",
        json={
            "lock_version": 1,
            "change_reason": "[샘플] 구성 삭제 후 교체",
            "variants": [variant("V9", 1_000_000, 10)],
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["lock_version"] == 2
    assert [v["variant_code"] for v in res.json()["variants"]] == ["V9"]


def test_stale_lock_version_is_conflict(client: TestClient) -> None:
    company_id = create_company(client)
    product = create_product(client, company_id)
    body = {"lock_version": 1, "change_reason": "[샘플] 첫 수정", "name": "[샘플] A"}
    assert client.patch(f"/api/products/{product['id']}", json=body).status_code == 200

    stale = {"lock_version": 1, "change_reason": "[샘플] 늦은 수정", "name": "[샘플] B"}
    res = client.patch(f"/api/products/{product['id']}", json=stale)

    assert res.status_code == 409
    assert res.json()["code"] == "VERSION_CONFLICT"
    assert client.get(f"/api/products/{product['id']}").json()["name"] == "[샘플] A"


def test_status_transitions(client: TestClient) -> None:
    company_id = create_company(client)
    product = create_product(client, company_id)

    res = client.post(
        f"/api/products/{product['id']}/status",
        json={"status": "ENDED", "lock_version": 1, "reason": "[샘플]"},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "INVALID_STATUS_TRANSITION"

    product = set_status(client, product, "ACTIVE")
    product = set_status(client, product, "ENDED")
    assert product["status"] == "ENDED"
    history = client.get(f"/api/products/{product['id']}/status-history").json()
    assert [(h["from_status"], h["to_status"]) for h in history] == [
        (None, "DRAFT"),
        ("DRAFT", "ACTIVE"),
        ("ACTIVE", "ENDED"),
    ]


def test_ended_product_rejects_edit_and_status_change(client: TestClient) -> None:
    """A11: 종료 상품의 편집 API 직접 호출은 거부되고 자료는 그대로다."""
    company_id = create_company(client)
    product = create_product(client, company_id)
    product = set_status(client, product, "ACTIVE")
    ended = set_status(client, product, "ENDED")

    res = client.patch(
        f"/api/products/{ended['id']}",
        json={"lock_version": ended["lock_version"], "change_reason": "[샘플]", "name": "변경"},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "PRODUCT_ENDED"

    res = client.post(
        f"/api/products/{ended['id']}/status",
        json={"status": "ACTIVE", "lock_version": ended["lock_version"], "reason": "[샘플]"},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "PRODUCT_ENDED"

    assert client.get(f"/api/products/{ended['id']}").json() == ended
    assert len(client.get(f"/api/products/{ended['id']}/revisions").json()) == 1


def test_list_filters_by_status_and_query(client: TestClient) -> None:
    company_id = create_company(client)
    draft = create_product(client, company_id, product_code="P-DRAFT", name="[샘플] 초안")
    active = create_product(client, company_id, product_code="P-ACTIVE", name="[샘플] 판매중")
    set_status(client, active, "ACTIVE")

    res = client.get("/api/products", params={"status": "ACTIVE"})
    assert [p["product_code"] for p in res.json()] == ["P-ACTIVE"]
    assert res.json()[0]["variant_count"] == 1

    res = client.get("/api/products", params={"q": "초안"})
    assert [p["id"] for p in res.json()] == [draft["id"]]

    res = client.get("/api/products", params={"q": "%"})
    assert res.json() == []


def test_unknown_product_is_404(client: TestClient) -> None:
    res = client.get("/api/products/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"
