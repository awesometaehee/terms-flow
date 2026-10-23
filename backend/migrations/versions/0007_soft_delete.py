"""모듈·변수 삭제: 이력이 참조하므로 행을 지우지 않고 deleted_at으로 숨긴다

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clauses", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("variables", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("variables", "deleted_at")
    op.drop_column("clauses", "deleted_at")
