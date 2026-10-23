"""DB 트리거와 서비스 계층의 ENDED·불변 보호. API를 우회한 직접 변경도 막혀야 한다."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError
from app.services.document_sets import reserve_document_set_version
from tests.helpers import create_company, create_product, set_status


def _ended_product(client: TestClient) -> dict[str, Any]:
    product = create_product(client, create_company(client))
    product = set_status(client, product, "ACTIVE")
    return set_status(client, product, "ENDED")


def _expect_restrict(session: Session, sql: str, **params: Any) -> None:
    with pytest.raises(IntegrityError) as exc_info:
        session.execute(text(sql), params)
    session.rollback()
    assert getattr(exc_info.value.orig, "sqlstate", None) == "23001"


def test_product_revision_rows_are_immutable(client: TestClient, session: Session) -> None:
    product = create_product(client, create_company(client))
    pid = uuid.UUID(product["id"])

    _expect_restrict(
        session,
        "UPDATE product_revisions SET change_reason = 'x' WHERE product_id = :pid",
        pid=pid,
    )
    _expect_restrict(session, "DELETE FROM product_revisions WHERE product_id = :pid", pid=pid)


def test_ended_product_rows_cannot_change_in_db(client: TestClient, session: Session) -> None:
    ended = _ended_product(client)
    pid = uuid.UUID(ended["id"])

    _expect_restrict(session, "UPDATE products SET status = 'ACTIVE' WHERE id = :pid", pid=pid)
    _expect_restrict(
        session, "UPDATE product_variants SET price_amount = 1 WHERE product_id = :pid", pid=pid
    )
    _expect_restrict(session, "DELETE FROM product_variants WHERE product_id = :pid", pid=pid)
    _expect_restrict(
        session,
        """
        INSERT INTO product_revisions (id, product_id, revision_no, snapshot_jsonb, change_reason)
        VALUES (:id, :pid, 99, '{}', 'x')
        """,
        id=uuid.uuid4(),
        pid=pid,
    )
    assert client.get(f"/api/products/{ended['id']}").json() == ended


def test_document_set_reservation(client: TestClient, session: Session) -> None:
    product = create_product(client, create_company(client))
    product = set_status(client, product, "ACTIVE")
    pid = uuid.UUID(product["id"])

    first = reserve_document_set_version(session, pid, "[샘플] 최초 발행")
    second = reserve_document_set_version(session, pid, "[샘플] 재발행")
    session.commit()

    assert (first.version_no, second.version_no) == (1, 2)
    assert first.status == "PENDING"
    assert first.manifest["product_revision_no"] == 1

    listed = client.get(f"/api/products/{product['id']}/document-sets").json()
    assert [v["version_no"] for v in listed] == [2, 1]
    detail = client.get(f"/api/document-sets/{first.id}").json()
    assert detail["manifest"]["product_revision_id"] == str(first.product_revision_id)
    assert detail["files"] == []


def test_ended_product_cannot_get_new_document_set(client: TestClient, session: Session) -> None:
    ended = _ended_product(client)
    pid = uuid.UUID(ended["id"])

    with pytest.raises(ConflictError) as exc_info:
        reserve_document_set_version(session, pid, "[샘플]")
    assert exc_info.value.code == "PRODUCT_ENDED"
    session.rollback()

    revision_id = session.execute(
        text("SELECT id FROM product_revisions WHERE product_id = :pid"), {"pid": pid}
    ).scalar_one()
    _expect_restrict(
        session,
        """
        INSERT INTO document_set_versions
            (id, product_id, version_no, product_revision_id, manifest_jsonb, status, change_reason)
        VALUES (:id, :pid, 1, :rid, '{}', 'PENDING', 'x')
        """,
        id=uuid.uuid4(),
        pid=pid,
        rid=revision_id,
    )


def test_published_document_set_is_immutable(client: TestClient, session: Session) -> None:
    product = create_product(client, create_company(client))
    version = reserve_document_set_version(session, uuid.UUID(product["id"]), "[샘플]")
    session.commit()

    # PENDING 상태는 렌더링 결과를 채우기 위해 수정할 수 있다.
    session.execute(
        text(
            "UPDATE document_set_versions SET status = 'PUBLISHED', published_at = now() "
            "WHERE id = :id"
        ),
        {"id": version.id},
    )
    session.execute(
        text(
            """
            INSERT INTO document_files (id, document_set_version_id, document_type, format,
                page_no, storage_key, sha256, size_bytes)
            VALUES (:fid, :vid, 'TERMS', 'PDF', NULL, :key, :sha, 10)
            """
        ),
        {
            "fid": uuid.uuid4(),
            "vid": version.id,
            "key": f"test/{uuid.uuid4()}.pdf",
            "sha": "0" * 64,
        },
    )
    session.commit()

    _expect_restrict(
        session,
        "UPDATE document_set_versions SET change_reason = 'x' WHERE id = :id",
        id=version.id,
    )
    _expect_restrict(session, "DELETE FROM document_set_versions WHERE id = :id", id=version.id)
    _expect_restrict(
        session,
        "UPDATE document_files SET sha256 = :sha WHERE document_set_version_id = :id",
        id=version.id,
        sha="1" * 64,
    )

    detail = client.get(f"/api/products/{product['id']}").json()
    assert detail["latest_document_set_version_no"] == 1
