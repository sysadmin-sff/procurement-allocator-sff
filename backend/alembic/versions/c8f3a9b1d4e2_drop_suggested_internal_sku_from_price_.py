"""drop suggested_internal_sku from price list entries

Revision ID: c8f3a9b1d4e2
Revises: 1d82548b7a2c
Create Date: 2026-08-27 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8f3a9b1d4e2"
down_revision: str | None = "1d82548b7a2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("price_list_entries", "suggested_internal_sku")


def downgrade() -> None:
    op.add_column(
        "price_list_entries",
        sa.Column("suggested_internal_sku", sa.String(100), nullable=True),
    )
