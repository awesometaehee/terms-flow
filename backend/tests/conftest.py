"""테스트는 개발 DB·저장소가 아닌 별도 DB({POSTGRES_DB}_test)와 저장소를 쓴다.

DB가 없으면 만들고 Alembic 마이그레이션을 적용한다. 각 테스트 전에 업무 테이블을 비운다.
실행: cd backend && uv run pytest   (Chromium이 없으면 렌더링 테스트는 건너뜀)
"""

import os

_dev_db = os.environ.get("POSTGRES_DB", "terms_flow")
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", f"{_dev_db}_test")
_dev_bucket = os.environ.get("S3_BUCKET", "terms-flow-documents")
os.environ["S3_BUCKET"] = os.environ.get("TEST_S3_BUCKET", f"{_dev_bucket}-test")
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["STORAGE_LOCAL_DIR"] = os.environ.get(
    "TEST_STORAGE_LOCAL_DIR", os.path.join(_repo_root, "data", "storage-test")
)

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from psycopg import sql  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.storage import ensure_bucket  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
BUSINESS_TABLES = (
    "bulk_update_items",
    "bulk_update_jobs",
    "document_files",
    "document_set_versions",
    "product_revisions",
    "product_status_history",
    "product_variants",
    "products",
    "companies",
    "template_clause_rules",
    "template_revisions",
    "templates",
    "clause_revisions",
    "clauses",
    "publication_files",
    "publications",
    "document_revisions",
    "document_blocks",
    "document_tags",
    "clause_tags",
    "documents",
    "variables",
    "tags",
    "categories",
    "drafts",
    "images",
    "procrastinate_jobs",
)


@pytest.fixture(scope="session", autouse=True)
def _test_database() -> None:
    settings = get_settings()
    assert settings.postgres_db.endswith("_test"), "테스트는 *_test DB에서만 실행한다."
    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        dbname="postgres",
        autocommit=True,
    ) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (settings.postgres_db,)
        ).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(settings.postgres_db)))
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
    ensure_bucket()


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    # TRUNCATE는 행 단위 트리거(불변·ENDED 보호)를 실행하지 않는다.
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(BUSINESS_TABLES)} CASCADE"))


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session() -> Iterator[Session]:
    with get_sessionmaker()() as s:
        yield s
