"""자동 임시저장본: 보관·덮어쓰기·목록·삭제. 값은 [샘플]."""

import uuid

from fastapi.testclient import TestClient


def test_draft_put_get_overwrite_delete(client: TestClient) -> None:
    key = f"module:{uuid.uuid4()}"
    assert client.get(f"/api/drafts/{key}").status_code == 404
    res = client.put(f"/api/drafts/{key}", json={"base": "3", "value": {"title": "[샘플] 임시"}})
    assert res.status_code == 200, res.text
    assert client.get(f"/api/drafts/{key}").json()["value"] == {"title": "[샘플] 임시"}

    client.put(f"/api/drafts/{key}", json={"base": "4", "value": {"title": "[샘플] 고침"}})
    got = client.get(f"/api/drafts/{key}").json()
    assert (got["base"], got["value"]["title"]) == ("4", "[샘플] 고침")

    assert client.delete(f"/api/drafts/{key}").status_code == 204
    assert client.get(f"/api/drafts/{key}").status_code == 404
    assert client.delete(f"/api/drafts/{key}").status_code == 204  # 없어도 성공


def test_new_module_drafts_are_listed(client: TestClient) -> None:
    a, b = f"module-new:{uuid.uuid4().hex}", f"module-new:{uuid.uuid4().hex}"
    client.put(f"/api/drafts/{a}", json={"base": "new", "value": {}, "title": "[샘플] 가"})
    client.put(f"/api/drafts/{b}", json={"base": "new", "value": {}, "title": "[샘플] 나"})
    client.put(f"/api/drafts/document:{uuid.uuid4()}", json={"base": "1", "value": {}})
    listed = client.get("/api/drafts", params={"prefix": "module-new:"}).json()
    assert [d["title"] for d in listed][:2] == ["[샘플] 나", "[샘플] 가"]
    assert all(d["key"].startswith("module-new:") for d in listed)


def test_rejects_bad_keys_and_bodies(client: TestClient) -> None:
    assert client.put("/api/drafts/other:abc", json={"base": "1", "value": {}}).status_code == 422
    key = f"module:{uuid.uuid4()}"
    assert client.put(f"/api/drafts/{key}", json={"value": {}}).status_code == 422
    big = {"base": "1", "value": {"x": "가" * (2 * 1024 * 1024)}}  # UTF-8로 6MB
    assert client.put(f"/api/drafts/{key}", json=big).status_code == 422
