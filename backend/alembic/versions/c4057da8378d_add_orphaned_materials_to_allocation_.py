"""add orphaned_materials to allocation_runs

Revision ID: c4057da8378d
Revises: 799b1a2dfae9
Create Date: 2026-08-17 19:13:42.737663

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4057da8378d"
down_revision: str | None = "799b1a2dfae9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "allocation_runs",
        sa.Column("orphaned_materials", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.alter_column("allocation_runs", "orphaned_materials", server_default=None)


def downgrade() -> None:
    op.drop_column("allocation_runs", "orphaned_materials")
