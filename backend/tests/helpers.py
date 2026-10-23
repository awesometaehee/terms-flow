"""테스트용 입력 데이터. 모든 값은 [샘플]이며 실제 상품·법인·조항이 아니다."""

import copy
import os
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

# 개발 가이드 4장의 구조 설명용 예시를 줄인 것.
COMPOSITION: dict[str, Any] = {
    "schemaVersion": 1,
    "groups": [
        {
            "id": "funeral_goods",
            "label": "고인 용품",
            "order": 10,
            "items": [
                {
                    "id": "coffin",
                    "label": "관",
                    "specification": "[샘플] 규격",
                    "quantity": {"value": 1, "unit": "개"},
                    "notes": [],
                    "order": 10,
                },
                {
                    "id": "shroud",
                    "label": "수의",
                    "specification": None,
                    "quantity": None,
                    "order": 20,
                    "children": [{"id": "shroud_part", "label": "[샘플] 하위 항목", "order": 10}],
                },
            ],
        }
    ],
    "footnotes": ["[샘플] 주석"],
}


def composition(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(COMPOSITION)
    data.update(changes)
    return data


def variant(code: str, price: int, sort_order: int, **changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "variant_code": code,
        "display_name": f"[샘플] {code}",
        "price_amount": price,
        "sort_order": sort_order,
        "composition": composition(),
    }
    data.update(changes)
    return data


def create_company(client: TestClient, code: str = "SAMPLE-CO") -> str:
    res = client.post("/api/companies", json={"code": code, "name": "[샘플] 법인"})
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


def product_payload(company_id: str, **changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "product_code": "P001",
        "name": "[샘플] 상품",
        "company_id": company_id,
        "channel": "OFFLINE",
        "refund_type": "SAMPLE_REFUND",
        "bundle_type": "STANDARD",
        "variants": [variant("V1", 3_000_000, 10)],
    }
    data.update(changes)
    return data


def create_product(client: TestClient, company_id: str, **changes: Any) -> dict[str, Any]:
    res = client.post("/api/products", json=product_payload(company_id, **changes))
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    return body


def set_status(client: TestClient, product: dict[str, Any], status: str) -> dict[str, Any]:
    res = client.post(
        f"/api/products/{product['id']}/status",
        json={"status": status, "lock_version": product["lock_version"], "reason": "[샘플] 사유"},
    )
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def error_paths(body: dict[str, Any]) -> list[str]:
    return [e["path"] for e in body["errors"]]


def renderer_available() -> bool:
    """Playwright Chromium이 설치되어 있으면 True (`playwright install chromium`)."""
    custom = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if custom:
        root = Path(custom)
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    else:
        root = Path.home() / ".cache" / "ms-playwright"
    return any(root.glob("chromium*"))
