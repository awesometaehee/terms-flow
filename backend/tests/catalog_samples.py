"""테스트용 조항·템플릿. 모든 문구는 [샘플]이며 실제 약관 문구가 아니다."""

from typing import Any

from fastapi.testclient import TestClient

TERMS_LAYOUT: dict[str, Any] = {
    "schemaVersion": 1,
    "blocks": [
        {"type": "heading", "text": "{{ product.name }} 약관"},
        {
            "type": "paragraph",
            "text": "[샘플] {{ company.name }}이(가) 제공하는 상품의 약관입니다.",
        },
        {"type": "clauses", "numbering": "article"},
    ],
}
SUMMARY_LAYOUT: dict[str, Any] = {
    "schemaVersion": 1,
    "blocks": [
        {"type": "heading", "text": "{{ product.name }} 약관 주요 내용"},
        {"type": "paragraph", "text": "[샘플] 주요 내용 요약 문단\n두 번째 줄"},
        {"type": "variant_prices"},
    ],
}
DESCRIPTION_LAYOUT: dict[str, Any] = {
    "schemaVersion": 1,
    "blocks": [
        {"type": "heading", "text": "{{ product.name }} 상품설명서"},
        {"type": "variant_table"},
        {"type": "clauses", "numbering": "none"},
    ],
}

# (clause_key, document_type, kind, title, content)
CLAUSES = [
    ("terms.purpose", "TERMS", "COMMON", "목적", "[샘플] {{ product.name }} 목적 조항"),
    ("terms.partner_fee", "TERMS", "CONDITIONAL", "협력비", "[샘플] 협력비 조항"),
    ("terms.refund_a", "TERMS", "CONDITIONAL", "환급 A", "[샘플] 환급 방식 A 조항"),
    ("terms.refund_b", "TERMS", "CONDITIONAL", "환급 B", "[샘플] 환급 방식 B 조항"),
    ("terms.bundle", "TERMS", "CONDITIONAL", "결합 상품", "[샘플] 결합 상품 조항"),
    ("terms.notice", "TERMS", "COMMON", "안내", "[샘플] 선택 안내 조항"),
    ("desc.bundle_notice", "PRODUCT_DESCRIPTION", "CONDITIONAL", "결합 안내", "[샘플] 결합 안내"),
]

TERMS_RULES = [
    {"clause_key": "terms.purpose", "sort_order": 10},
    {"clause_key": "terms.partner_fee", "sort_order": 20, "condition": {"channel": ["OFFLINE"]}},
    {"clause_key": "terms.refund_a", "sort_order": 30, "condition": {"refund_type": ["REFUND_A"]}},
    {"clause_key": "terms.refund_b", "sort_order": 30, "condition": {"refund_type": ["REFUND_B"]}},
    {"clause_key": "terms.bundle", "sort_order": 40, "condition": {"bundle_type": ["BUNDLE"]}},
    {"clause_key": "terms.notice", "sort_order": 50, "required": False},
]


def _post(client: TestClient, url: str, body: dict[str, Any]) -> dict[str, Any]:
    res = client.post(url, json=body)
    assert res.status_code == 201, res.text
    data: dict[str, Any] = res.json()
    return data


def setup_catalog(client: TestClient) -> dict[str, str]:
    """조항 7개와 템플릿 4개(약관, 주요 내용, 일반형·결합형 설명서)를 만든다. clause_key→id"""
    ids = {}
    for key, doc_type, kind, title, content in CLAUSES:
        clause = _post(
            client,
            "/api/clauses",
            {
                "clause_key": key,
                "document_type": doc_type,
                "kind": kind,
                "title": title,
                "content": content,
            },
        )
        ids[key] = clause["id"]
    templates: list[dict[str, Any]] = [
        {
            "template_key": "terms.standard",
            "document_type": "TERMS",
            "layout_definition": TERMS_LAYOUT,
            "clause_rules": TERMS_RULES,
        },
        {
            "template_key": "summary.standard",
            "document_type": "TERMS_SUMMARY",
            "layout_definition": SUMMARY_LAYOUT,
        },
        {
            "template_key": "description.standard",
            "document_type": "PRODUCT_DESCRIPTION",
            "layout_definition": DESCRIPTION_LAYOUT,
            "selection_condition": {"bundle_type": ["STANDARD"]},
        },
        {
            "template_key": "description.bundle",
            "document_type": "PRODUCT_DESCRIPTION",
            "layout_definition": DESCRIPTION_LAYOUT,
            "selection_condition": {"bundle_type": ["BUNDLE"]},
            "clause_rules": [{"clause_key": "desc.bundle_notice", "sort_order": 10}],
        },
    ]
    for template in templates:
        ids[template["template_key"]] = _post(
            client, "/api/templates", {"name": "[샘플] 템플릿", **template}
        )["id"]
    return ids
