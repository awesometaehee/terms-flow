"""Procrastinate 작업 큐 스키마 (3.10.0)

Revision ID: 0001
Revises:
Create Date: 2026-10-22

uv.lock에 고정된 Procrastinate 버전의 스키마를 SQL 파일로 고정해 적용한다.
Procrastinate를 업그레이드할 때는 해당 버전의 마이그레이션 SQL을 새 리비전으로 추가한다.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = Path(__file__).resolve().parents[1] / "sql" / "procrastinate_3.10.0.sql"


def upgrade() -> None:
    # 함수 본문의 '%'가 바인딩 파라미터로 해석되지 않도록
    # 파라미터 없이 psycopg 연결에 직접 실행한다. 같은 트랜잭션 안에서 실행된다.
    driver_connection = op.get_bind().connection.driver_connection
    assert driver_connection is not None
    driver_connection.execute(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("작업 큐 스키마는 되돌리지 않는다.")
