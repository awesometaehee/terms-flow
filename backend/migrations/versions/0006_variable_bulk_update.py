"""변수 값 일괄 반영: 일괄 작업이 모듈 리비전 대신 변수 값을 가리킬 수 있게 한다

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("bulk_update_jobs", "clause_id", nullable=True)
    op.alter_column("bulk_update_jobs", "clause_revision_id", nullable=True)
    op.add_column(
        "bulk_update_jobs",
        sa.Column("variable_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # 반영한 기본값 (작업 시점 값을 남긴다)
    op.add_column("bulk_update_jobs", sa.Column("variable_value", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("fk_bulk_update_jobs_variable_id_variables"),
        "bulk_update_jobs",
        "variables",
        ["variable_id"],
        ["id"],
    )
    op.create_check_constraint(
        op.f("ck_bulk_update_jobs_one_source"),
        "bulk_update_jobs",
        "(clause_id IS NULL) <> (variable_id IS NULL)"
        " AND (clause_id IS NULL) = (clause_revision_id IS NULL)",
    )


def downgrade() -> None:
    # 발행본이 작업을 참조하고 발행본은 고칠 수 없으므로, 변수 작업이 있으면 되돌리지 않는다.
    # (NOT NULL 복원이 실패하며 중단된다.)
    op.drop_constraint(op.f("ck_bulk_update_jobs_one_source"), "bulk_update_jobs", type_="check")
    op.drop_constraint(
        op.f("fk_bulk_update_jobs_variable_id_variables"), "bulk_update_jobs", type_="foreignkey"
    )
    op.drop_column("bulk_update_jobs", "variable_value")
    op.drop_column("bulk_update_jobs", "variable_id")
    op.alter_column("bulk_update_jobs", "clause_revision_id", nullable=False)
    op.alter_column("bulk_update_jobs", "clause_id", nullable=False)
