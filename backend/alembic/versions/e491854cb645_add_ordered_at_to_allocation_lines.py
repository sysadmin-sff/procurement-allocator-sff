"""add ordered_at to allocation_lines (ADR-0007)

Revision ID: e491854cb645
Revises: b2e5f8a1c3d7
Create Date: 2026-08-18 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e491854cb645"
down_revision: str | None = "b2e5f8a1c3d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "allocation_lines",
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("allocation_lines", "ordered_at")
