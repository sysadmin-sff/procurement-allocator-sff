"""add material embedding column

Revision ID: f1a6780bb7da
Revises: a7c1f4b2e8d9
Create Date: 2026-08-25 21:42:14.326249

"""
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "f1a6780bb7da"
down_revision: str | None = "a7c1f4b2e8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "materials",
        sa.Column("embedding", Vector(1536), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("materials", "embedding")
