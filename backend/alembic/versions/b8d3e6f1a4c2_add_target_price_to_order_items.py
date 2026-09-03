"""add target_price to order_items (ADR-0027)

Revision ID: b8d3e6f1a4c2
Revises: c8f3a9b1d4e2
Create Date: 2026-09-03 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8d3e6f1a4c2"
down_revision: str | None = "c8f3a9b1d4e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("target_price", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "target_price")
