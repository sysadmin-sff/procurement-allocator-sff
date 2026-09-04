"""add split_categories to allocation_runs

Revision ID: 5eeff6d921a9
Revises: b8d3e6f1a4c2
Create Date: 2026-09-04 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5eeff6d921a9"
down_revision: str | None = "b8d3e6f1a4c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "allocation_runs",
        sa.Column("split_categories", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.alter_column("allocation_runs", "split_categories", server_default=None)


def downgrade() -> None:
    op.drop_column("allocation_runs", "split_categories")
