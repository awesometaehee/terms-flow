"""KMS 테스트용 입력. 모든 문구는 [샘플]이며 실제 약관 문구가 아니다."""

import uuid
from typing import Any

from fastapi.testclient import TestClient


def text(value: str, *marks: str) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": value}
    if marks:
        node["marks"] = [{"type": m} for m in marks]
    return node


def var(key: str) -> dict[str, Any]:
    return {"type": "variable", "attrs": {"key": key}}


def doc(*paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "doc", "content": [{"type": "paragraph", "content": p} for p in paragraphs]}


def post(client: TestClient, url: str, body: dict[str, Any], status: int = 201) -> dict[str, Any]:
    res = client.post(url, json=body)
    assert res.status_code == status, res.text
    data: dict[str, Any] = res.json()
    return data


def create_variable(client: TestClient, key: str, label: str, default: str | None = None) -> None:
    post(client, "/api/variables", {"key": key, "label": label, "default_value": default})


def create_module(
    client: TestClient, key: str, content_json: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    return post(
        client,
        "/api/clauses",
        {"clause_key": key, "title": f"[샘플] {key}", "content_json": content_json, **extra},
    )


def module_block(
    module: dict[str, Any], content_json: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "kind": "MODULE",
        "clause_id": module["id"],
        "clause_revision_no": module["latest_revision_no"],
        "content_json": content_json,
    }


def text_block(content_json: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "kind": "TEXT", "content_json": content_json}


def create_document(client: TestClient, title: str = "[샘플] 문서", **extra: Any) -> dict[str, Any]:
    return post(client, "/api/documents", {"title": title, **extra})


def save(
    client: TestClient,
    document: dict[str, Any],
    blocks: list[dict[str, Any]],
    status: int = 200,
    **extra: Any,
) -> dict[str, Any]:
    body = {
        "lock_version": document["lock_version"],
        "title": document["title"],
        "blocks": blocks,
        **extra,
    }
    res = client.put(f"/api/documents/{document['id']}", json=body)
    assert res.status_code == status, res.text
    data: dict[str, Any] = res.json()
    return data


def set_status(client: TestClient, document: dict[str, Any], status: str) -> dict[str, Any]:
    return post(
        client,
        f"/api/documents/{document['id']}/status",
        {"status": status, "lock_version": document["lock_version"], "reason": "[샘플]"},
        status=200,
    )
