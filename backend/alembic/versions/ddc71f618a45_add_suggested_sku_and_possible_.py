"""add suggested sku and possible duplicate of to price list entries

Revision ID: ddc71f618a45
Revises: f1a6780bb7da
Create Date: 2026-08-25 23:42:04.537170

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ddc71f618a45"
down_revision: str | None = "f1a6780bb7da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "price_list_entries",
        sa.Column("suggested_internal_sku", sa.String(100), nullable=True),
    )
    op.add_column(
        "price_list_entries",
        sa.Column("possible_duplicate_of", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_list_entries", "possible_duplicate_of")
    op.drop_column("price_list_entries", "suggested_internal_sku")
