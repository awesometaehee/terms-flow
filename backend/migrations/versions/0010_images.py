"""이미지 자료실: 올린 이미지 목록 (이름·크기). 파일 자체는 저장소 assets/에 있다

함께: 문서의 '원본 그대로' 단락 본문을 JSON null에서 SQL NULL로 바꾼다 (IS NULL 조건이 맞게).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "images",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        # 본문 이미지 노드의 src (/api/assets/<파일>). 파일은 바꾸지 않는다.
        sa.Column("url", sa.String(200), nullable=False, unique=True),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # 자료실에서 지운 이미지: 목록에서 빠진다. 이전 본문·발행본이 쓰므로 파일은 남긴다.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_images_created_at", "images", ["created_at"])

    # 종료 문서 보호 트리거를 이 변환 동안만 끈다 (값의 의미는 같고 표현만 바뀐다).
    op.execute("ALTER TABLE document_blocks DISABLE TRIGGER trg_document_blocks_ended_document")
    op.execute("UPDATE document_blocks SET content_json = NULL WHERE content_json = 'null'::jsonb")
    op.execute("ALTER TABLE document_blocks ENABLE TRIGGER trg_document_blocks_ended_document")


def downgrade() -> None:
    op.drop_index("ix_images_created_at", table_name="images")
    op.drop_table("images")
