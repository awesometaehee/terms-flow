"""KMS: 분류·변수·모듈·문서 조합·문서 안 수정·원본 반영·검색·종료 문서 보호."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as sql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.helpers import error_paths
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
    text_block,
    var,
)


@pytest.fixture
def modules(client: TestClient) -> dict[str, dict[str, Any]]:
    create_variable(client, "service_name", "서비스명")
    create_variable(client, "min_age", "가입 연령", default="14")
    category = post(client, "/api/categories", {"name": "[샘플] 이용약관"})
    child = post(client, "/api/categories", {"name": "[샘플] 가입", "parent_id": category["id"]})
    purpose = create_module(
        client,
        "kms.purpose",
        doc([text("[샘플] 본 약관은 "), var("service_name"), text(" 이용 조건을 정한다.")]),
        category_id=category["id"],
        tags=["공통", "목적"],
    )
    join = create_module(
        client,
        "kms.join",
        doc([text("[샘플] 만 "), var("min_age"), text("세 이상 가입")]),
        category_id=child["id"],
        tags=["공통"],
    )
    return {"purpose": purpose, "join": join, "category": category, "child": child}


def test_categories_tags_and_module_filters(client: TestClient, modules: dict[str, Any]) -> None:
    category, child = modules["category"], modules["child"]
    listed = client.get("/api/clauses", params={"category_id": category["id"]}).json()
    assert sorted(m["clause_key"] for m in listed) == ["kms.join", "kms.purpose"]  # 하위 포함
    listed = client.get("/api/clauses", params={"category_id": child["id"]}).json()
    assert [m["clause_key"] for m in listed] == ["kms.join"]
    listed = client.get("/api/clauses", params={"tag": "목적"}).json()
    assert [m["clause_key"] for m in listed] == ["kms.purpose"]
    listed = client.get("/api/clauses", params={"q": "이용 조건"}).json()
    assert [m["clause_key"] for m in listed] == ["kms.purpose"]
    assert listed[0]["excerpt"] == "[샘플] 본 약관은 [서비스명] 이용 조건을 정한다."
    tags = {t["name"]: t["module_count"] for t in client.get("/api/tags").json()}
    assert tags == {"공통": 2, "목적": 1}

    res = client.delete(f"/api/categories/{category['id']}")
    assert res.status_code == 409
    res = client.patch(f"/api/categories/{category['id']}", json={"parent_id": child["id"]})
    assert res.status_code == 422  # 자기 하위로 이동 금지


def test_module_body_validation(client: TestClient, modules: dict[str, Any]) -> None:
    res = client.post(
        "/api/clauses",
        json={
            "clause_key": "kms.bad",
            "title": "[샘플]",
            "content_json": doc([var("unknown_var")]),
        },
    )
    assert res.status_code == 422
    assert error_paths(res.json()) == ["content_json"]
    res = client.post(
        "/api/clauses",
        json={
            "clause_key": "kms.bad",
            "title": "[샘플]",
            "content": "a",
            "content_json": doc([text("a")]),
        },
    )
    assert res.status_code == 422
    res = client.post("/api/variables", json={"key": "product.name", "label": "예약"})
    assert res.status_code == 409


def test_compose_reorder_and_modify_in_document(
    client: TestClient, modules: dict[str, Any]
) -> None:
    purpose, join = modules["purpose"], modules["join"]
    document = create_document(client, tags=["샘플문서"])
    original = purpose["revisions"][0]["content_json"] if "revisions" in purpose else None
    assert original is not None

    a, b = module_block(join), module_block(purpose, original)  # 원본과 같은 본문 → 수정 아님
    custom = text_block(doc([text("[샘플] 이 문서에만 있는 단락", "italic")]))
    saved = save(
        client,
        document,
        [a, b, custom],
        variable_values={"service_name": "[샘플]서비스"},
        change_reason="[샘플] 조합",
    )
    assert [blk["clause_key"] for blk in saved["blocks"]] == ["kms.join", "kms.purpose", None]
    assert [blk["modified"] for blk in saved["blocks"]] == [False, False, False]
    assert saved["revision_no"] == 2
    assert {v["key"] for v in saved["variables"]} == {"min_age", "service_name"}

    # 순서 변경 + 문서 안에서 모듈 본문 수정
    edited = doc([text("[샘플] 문서에서 고친 목적 조항 "), var("service_name")])
    saved = save(
        client,
        saved,
        [custom, module_block(purpose, edited), a],
        variable_values=saved["variable_values"],
    )
    assert [blk["id"] for blk in saved["blocks"]] == [
        custom["id"],
        saved["blocks"][1]["id"],
        a["id"],
    ]
    assert saved["blocks"][1]["modified"] is True
    assert saved["blocks"][1]["original_content_json"] == original

    html = client.get(f"/api/documents/{document['id']}/preview").text
    assert (
        html.index("이 문서에만 있는 단락")
        < html.index("문서에서 고친 목적 조항")
        < html.index("세 이상 가입")
    )
    assert '<span class="var">[샘플]서비스</span>' in html
    assert '<span class="var">14</span>' in html  # 기본값

    # 원본 모듈은 그대로
    assert client.get(f"/api/clauses/{purpose['id']}").json()["latest_revision_no"] == 1
    old = client.get(f"/api/documents/{document['id']}/revisions/2").json()
    assert [blk["clause_key"] for blk in old["snapshot"]["blocks"]] == [
        "kms.join",
        "kms.purpose",
        None,
    ]


def test_stale_save_and_invalid_blocks(client: TestClient, modules: dict[str, Any]) -> None:
    document = create_document(client)
    save(client, document, [module_block(modules["join"])])
    res = client.put(
        f"/api/documents/{document['id']}",
        json={"lock_version": document["lock_version"], "title": "x", "blocks": []},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "VERSION_CONFLICT"

    fresh = client.get(f"/api/documents/{document['id']}").json()
    bad_module = module_block(modules["join"]) | {"clause_revision_no": 99}
    bad_text = text_block({"type": "doc", "content": [{"type": "image"}]})
    res = client.put(
        f"/api/documents/{document['id']}",
        json={
            "lock_version": fresh["lock_version"],
            "title": "x",
            "blocks": [bad_module, bad_text],
            "variable_values": {"nope": "1"},
        },
    )
    assert res.status_code == 422
    assert error_paths(res.json()) == ["variable_values.nope"]
    res = client.put(
        f"/api/documents/{document['id']}",
        json={
            "lock_version": fresh["lock_version"],
            "title": "x",
            "blocks": [bad_module, bad_text],
        },
    )
    assert error_paths(res.json()) == [
        "blocks[0].clause_revision_no",
        "blocks[1].content_json.content[0].attrs.src",  # 이 시스템에 올린 이미지만
    ]


def test_promote_modified_block_to_module(client: TestClient, modules: dict[str, Any]) -> None:
    purpose = modules["purpose"]
    document = create_document(client)
    edited = doc([text("[샘플] 개선된 목적 "), var("service_name")])
    saved = save(client, document, [module_block(purpose, edited)])
    block_id = saved["blocks"][0]["id"]

    revision = post(
        client,
        f"/api/documents/{document['id']}/blocks/{block_id}/promote",
        {"lock_version": saved["lock_version"], "change_reason": "[샘플] 원본 반영"},
    )
    assert revision["revision_no"] == 2
    assert revision["content_json"] == edited
    detail = client.get(f"/api/documents/{document['id']}").json()
    assert (detail["blocks"][0]["modified"], detail["blocks"][0]["clause_revision_no"]) == (
        False,
        2,
    )
    latest = client.get(f"/api/documents/{document['id']}/revisions").json()[0]
    snapshot = client.get(
        f"/api/documents/{document['id']}/revisions/{latest['revision_no']}"
    ).json()["snapshot"]
    assert (snapshot["blocks"][0]["clause_revision_no"], snapshot["blocks"][0]["modified"]) == (
        2,
        False,
    )
    assert snapshot["blocks"][0]["content_json"] == edited

    # r1을 쓰는 다른 문서는 '새 버전 있음'으로 표시된다
    other = create_document(client, title="[샘플] 다른 문서")
    other_saved = save(client, other, [module_block(purpose) | {"clause_revision_no": 1}])
    assert (
        other_saved["blocks"][0]["outdated"],
        other_saved["blocks"][0]["latest_revision_no"],
    ) == (
        True,
        2,
    )


def test_promote_conflicts_when_module_changed(client: TestClient, modules: dict[str, Any]) -> None:
    purpose = modules["purpose"]
    document = create_document(client)
    saved = save(client, document, [module_block(purpose, doc([text("[샘플] 문서 수정")]))])
    post(
        client,
        f"/api/clauses/{purpose['id']}/revisions",
        {
            "base_revision_no": 1,
            "content_json": doc([text("[샘플] 다른 곳 수정")]),
            "change_reason": "[샘플]",
        },
    )
    res = client.post(
        f"/api/documents/{document['id']}/blocks/{saved['blocks'][0]['id']}/promote",
        json={"lock_version": saved["lock_version"], "change_reason": "[샘플]"},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "VERSION_CONFLICT"


def test_search_modules_and_documents(client: TestClient, modules: dict[str, Any]) -> None:
    document = create_document(client, title="[샘플] 회원 가입 안내")
    save(client, document, [text_block(doc([text("[샘플] 환불은 7일 이내 가능")]))])

    hits = client.get("/api/search", params={"q": "환불"}).json()["hits"]
    assert [(h["kind"], h["title"]) for h in hits] == [("DOCUMENT", "[샘플] 회원 가입 안내")]
    assert "환불은 7일" in hits[0]["excerpt"]
    hits = client.get("/api/search", params={"q": "세 이상"}).json()["hits"]
    assert [(h["kind"], h["title"]) for h in hits] == [("MODULE", "[샘플] kms.join")]
    hits = client.get("/api/search", params={"q": "100%"}).json()["hits"]
    assert hits == []


def test_ended_document_is_read_only(
    client: TestClient, session: Session, modules: dict[str, Any]
) -> None:
    document = create_document(client)
    saved = save(client, document, [module_block(modules["join"])])
    ended = set_status(client, set_status(client, saved, "ACTIVE"), "ENDED")

    res = client.put(
        f"/api/documents/{document['id']}",
        json={"lock_version": ended["lock_version"], "title": "x", "blocks": []},
    )
    assert res.status_code == 409
    assert res.json()["code"] == "DOCUMENT_ENDED"
    res = client.post(
        f"/api/documents/{document['id']}/publications", json={"change_reason": "[샘플]"}
    )
    assert res.status_code == 409

    with pytest.raises(IntegrityError):
        session.execute(
            sql("DELETE FROM document_blocks WHERE document_id = :id"),
            {"id": uuid.UUID(document["id"])},
        )
    session.rollback()
    with pytest.raises(IntegrityError):
        session.execute(
            sql("UPDATE document_revisions SET change_reason = 'x' WHERE document_id = :id"),
            {"id": uuid.UUID(document["id"])},
        )
    session.rollback()
    assert client.get(f"/api/documents/{document['id']}").json() == ended


def test_publish_requires_variable_values(client: TestClient, modules: dict[str, Any]) -> None:
    document = create_document(client)
    save(client, document, [module_block(modules["purpose"])])
    res = client.post(
        f"/api/documents/{document['id']}/publications", json={"change_reason": "[샘플]"}
    )
    assert res.status_code == 422
    assert error_paths(res.json()) == ["variable_values.service_name"]


def test_copy_document(client: TestClient, modules: dict[str, Any]) -> None:
    source = create_document(client, title="[샘플] 원본")
    saved = save(client, source, [module_block(modules["join"])], variable_values={"min_age": "19"})
    copy = create_document(client, title="[샘플] 복제", copy_from_document_id=source["id"])
    assert copy["variable_values"] == {"min_age": "19"}
    assert [b["clause_key"] for b in copy["blocks"]] == ["kms.join"]
    assert copy["blocks"][0]["id"] != saved["blocks"][0]["id"]
    assert copy["status"] == "DRAFT"


def test_delete_variable_only_when_unused(client: TestClient, modules: dict[str, Any]) -> None:
    unused = post(client, "/api/variables", {"key": "unused_var", "label": "[샘플] 안 쓰는 변수"})
    assert client.delete(f"/api/variables/{unused['id']}").status_code == 204

    used = next(v for v in client.get("/api/variables").json() if v["key"] == "service_name")
    res = client.delete(f"/api/variables/{used['id']}")
    assert res.status_code == 409
    assert res.json()["code"] == "VARIABLE_IN_USE"

    valued = post(client, "/api/variables", {"key": "valued_var", "label": "[샘플] 값만 입력"})
    document = create_document(client)
    save(client, document, [], variable_values={"valued_var": "x"})
    assert client.delete(f"/api/variables/{valued['id']}").status_code == 409


def test_variable_used_only_in_history_can_be_deleted(
    client: TestClient, modules: dict[str, Any]
) -> None:
    create_variable(client, "old_var", "[샘플] 예전 변수")
    module = create_module(client, "kms.old", doc([text("[샘플] "), var("old_var")]))
    old = next(v for v in client.get("/api/variables").json() if v["key"] == "old_var")
    assert client.delete(f"/api/variables/{old['id']}").status_code == 409

    # 최신 본문에서 빼면 예전 버전에 남아 있어도 지울 수 있다
    post(
        client,
        f"/api/clauses/{module['id']}/revisions",
        {
            "base_revision_no": 1,
            "content_json": doc([text("[샘플] 변수 없음")]),
            "change_reason": "x",
        },
    )
    assert client.delete(f"/api/variables/{old['id']}").status_code == 204
    assert "old_var" not in [v["key"] for v in client.get("/api/variables").json()]
    # 이전 버전 본문은 그대로 보이고, 새 본문에는 쓸 수 없다
    detail = client.get(f"/api/clauses/{module['id']}").json()
    assert detail["revisions"][0]["content_json"]["content"][0]["content"][1]["attrs"] == {
        "key": "old_var"
    }
    res = client.post(
        f"/api/clauses/{module['id']}/revisions",
        json={"base_revision_no": 2, "content_json": doc([var("old_var")]), "change_reason": "x"},
    )
    assert res.status_code == 422


def test_delete_module_only_when_unused(client: TestClient, modules: dict[str, Any]) -> None:
    join = modules["join"]
    document = create_document(client, title="[샘플] 가입 문서")
    saved = save(client, document, [module_block(join)])
    res = client.delete(f"/api/clauses/{join['id']}")
    assert res.status_code == 409
    assert res.json()["code"] == "CLAUSE_IN_USE"
    assert "[샘플] 가입 문서" in res.json()["message"]

    # 종료된 문서만 쓰면 삭제할 수 있고, 종료 문서는 그대로 남는다
    ended = set_status(client, set_status(client, saved, "ACTIVE"), "ENDED")
    assert client.delete(f"/api/clauses/{join['id']}").status_code == 204
    assert join["id"] not in [c["id"] for c in client.get("/api/clauses").json()]
    hits = client.get("/api/search", params={"q": "세 이상"}).json()["hits"]
    assert [h["kind"] for h in hits] == ["DOCUMENT"]
    assert client.get(f"/api/documents/{document['id']}").json() == ended
    assert client.get(f"/api/clauses/{join['id']}").json()["deleted"] is True

    # 삭제한 모듈은 새 문서에 넣거나 고칠 수 없다
    other = create_document(client)
    save(client, other, [module_block(join)], status=422)
    res = client.patch(f"/api/clauses/{join['id']}", json={"title": "x"})
    assert res.status_code == 409


def test_delete_document(client: TestClient, modules: dict[str, Any]) -> None:
    document = create_document(client, title="[샘플] 지울 문서")
    save(client, document, [module_block(modules["join"])])
    assert client.delete(f"/api/documents/{document['id']}").status_code == 204
    assert client.get(f"/api/documents/{document['id']}").status_code == 404
    assert document["id"] not in [d["id"] for d in client.get("/api/documents").json()]
    assert client.get("/api/search", params={"q": "지울 문서"}).json()["hits"] == []
    # 삭제한 문서는 모듈 삭제를 막지 않는다
    assert client.delete(f"/api/clauses/{modules['join']['id']}").status_code == 204

    ended = create_document(client, title="[샘플] 종료 문서")
    saved = save(client, ended, [module_block(modules["purpose"])])
    set_status(client, set_status(client, saved, "ACTIVE"), "ENDED")
    res = client.delete(f"/api/documents/{ended['id']}")
    assert res.status_code == 409
    assert res.json()["code"] == "DOCUMENT_ENDED"


def test_variable_used_by_unmodified_block_of_older_revision(
    client: TestClient, modules: dict[str, Any]
) -> None:
    # 문서가 원본 그대로 쓰는 예전 템플릿 버전에만 치환 항목이 남아 있어도 지울 수 없다
    create_variable(client, "old_only", "[샘플] 예전 버전에만")
    module = create_module(client, "kms.oldrev", doc([text("[샘플] "), var("old_only")]))
    document = create_document(client, title="[샘플] 예전 버전 문서")
    save(client, document, [module_block(module)])
    post(
        client,
        f"/api/clauses/{module['id']}/revisions",
        {"base_revision_no": 1, "content_json": doc([text("[샘플] 바뀜")]), "change_reason": "x"},
    )
    target = next(v for v in client.get("/api/variables").json() if v["key"] == "old_only")
    res = client.delete(f"/api/variables/{target['id']}")
    assert res.status_code == 409
    assert "[샘플] 예전 버전 문서" in res.json()["message"]
