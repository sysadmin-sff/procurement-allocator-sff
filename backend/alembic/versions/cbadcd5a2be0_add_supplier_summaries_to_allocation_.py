"""add supplier_summaries to allocation_runs

Revision ID: cbadcd5a2be0
Revises: c4057da8378d
Create Date: 2026-08-17 20:05:12.362500

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cbadcd5a2be0"
down_revision: str | None = "c4057da8378d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "allocation_runs",
        sa.Column("supplier_summaries", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.alter_column("allocation_runs", "supplier_summaries", server_default=None)


def downgrade() -> None:
    op.drop_column("allocation_runs", "supplier_summaries")
