"""add received_price and decline fields to order_items (ADR-0013)

Revision ID: 91375d2866f3
Revises: b15597e509ec
Create Date: 2026-08-20 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "91375d2866f3"
down_revision: str | None = "b15597e509ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("received_price", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("decline_reason", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "decline_reason")
    op.drop_column("order_items", "declined_at")
    op.drop_column("order_items", "received_price")
