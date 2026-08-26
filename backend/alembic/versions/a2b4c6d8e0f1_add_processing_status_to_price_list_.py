"""add processing_status to price list entries

Revision ID: a2b4c6d8e0f1
Revises: ddc71f618a45
Create Date: 2026-08-26 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2b4c6d8e0f1"
down_revision: str | None = "ddc71f618a45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_list_entries",
        sa.Column("processing_status", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_list_entries", "processing_status")
