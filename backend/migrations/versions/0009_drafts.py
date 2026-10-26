"""자동 임시저장본: 저장하지 않은 편집 내용을 서버에 보관해 다른 PC에서도 이어 쓴다

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "drafts",
        # "module:<id>", "document:<id>", "module-new:<id>"
        sa.Column("key", sa.String(100), primary_key=True),
        # 임시본을 만들 때의 서버 상태 (모듈 리비전 번호·문서 lock_version)
        sa.Column("base", sa.String(50), nullable=False),
        sa.Column("value_jsonb", postgresql.JSONB(), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("drafts")
