from typing import Any

from fastapi.testclient import TestClient

from tests.catalog_samples import TERMS_LAYOUT
from tests.helpers import error_paths


def _create_clause(client: TestClient, key: str, document_type: str = "TERMS") -> dict[str, Any]:
    res = client.post(
        "/api/clauses",
        json={
            "clause_key": key,
            "document_type": document_type,
            "kind": "COMMON",
            "title": "[샘플] 조항",
            "content": "[샘플] 조항 본문 1",
        },
    )
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    return body


def test_clause_revisions_are_appended(client: TestClient) -> None:
    clause = _create_clause(client, "common.purpose")
    assert clause["latest_revision_no"] == 1

    res = client.post(
        f"/api/clauses/{clause['id']}/revisions",
        json={"base_revision_no": 1, "content": "[샘플] 조항 본문 2", "change_reason": "[샘플]"},
    )
    assert res.status_code == 201
    assert res.json()["revision_no"] == 2

    detail = client.get(f"/api/clauses/{clause['id']}").json()
    assert [(r["revision_no"], r["content"]) for r in detail["revisions"]] == [
        (1, "[샘플] 조항 본문 1"),
        (2, "[샘플] 조항 본문 2"),
    ]


def test_clause_revision_from_stale_base_is_conflict(client: TestClient) -> None:
    clause = _create_clause(client, "common.purpose")
    body = {"base_revision_no": 1, "content": "[샘플] A", "change_reason": "[샘플]"}
    assert client.post(f"/api/clauses/{clause['id']}/revisions", json=body).status_code == 201

    res = client.post(f"/api/clauses/{clause['id']}/revisions", json=body)

    assert res.status_code == 409
    assert res.json()["code"] == "VERSION_CONFLICT"


def test_duplicate_clause_key_is_conflict(client: TestClient) -> None:
    _create_clause(client, "common.purpose")
    res = client.post(
        "/api/clauses",
        json={
            "clause_key": "common.purpose",
            "document_type": "TERMS",
            "kind": "COMMON",
            "title": "[샘플]",
            "content": "[샘플]",
        },
    )
    assert res.status_code == 409


def test_template_with_clause_rules_and_new_revision(client: TestClient) -> None:
    _create_clause(client, "common.purpose")
    _create_clause(client, "channel.partner_fee")
    res = client.post(
        "/api/templates",
        json={
            "template_key": "terms.standard",
            "document_type": "TERMS",
            "name": "[샘플] 약관",
            "layout_definition": TERMS_LAYOUT,
            "clause_rules": [
                {"clause_key": "common.purpose", "sort_order": 10},
                {
                    "clause_key": "channel.partner_fee",
                    "sort_order": 20,
                    "condition": {"channel": ["OFFLINE"]},
                    "required": False,
                },
            ],
        },
    )
    assert res.status_code == 201, res.text
    template = res.json()
    rules = template["revisions"][0]["clause_rules"]
    assert [(r["clause_key"], r["sort_order"], r["required"]) for r in rules] == [
        ("common.purpose", 10, True),
        ("channel.partner_fee", 20, False),
    ]

    res = client.post(
        f"/api/templates/{template['id']}/revisions",
        json={
            "base_revision_no": 1,
            "layout_definition": {"schemaVersion": 1, "blocks": [{"type": "clauses"}]},
            "clause_rules": [{"clause_key": "common.purpose", "sort_order": 10}],
            "change_reason": "[샘플] 협력비 조항 제외",
        },
    )
    assert res.status_code == 201, res.text
    revisions = res.json()["revisions"]
    assert [len(r["clause_rules"]) for r in revisions] == [2, 1]
    assert revisions[0]["layout_definition"] == TERMS_LAYOUT


def test_template_rule_validation(client: TestClient) -> None:
    _create_clause(client, "common.purpose")
    _create_clause(client, "summary.intro", document_type="TERMS_SUMMARY")
    res = client.post(
        "/api/templates",
        json={
            "template_key": "terms.standard",
            "document_type": "TERMS",
            "name": "[샘플] 약관",
            "layout_definition": TERMS_LAYOUT,
            "clause_rules": [
                {"clause_key": "common.purpose", "sort_order": 10},
                {"clause_key": "missing.clause", "sort_order": 20},
                {"clause_key": "summary.intro", "sort_order": 30},
                {"clause_key": "common.purpose", "sort_order": 40},
            ],
        },
    )
    assert res.status_code == 422
    assert error_paths(res.json()) == [
        "clause_rules[1].clause_key",
        "clause_rules[2].clause_key",
        "clause_rules[3].clause_key",
    ]
    assert client.get("/api/templates").json() == []
