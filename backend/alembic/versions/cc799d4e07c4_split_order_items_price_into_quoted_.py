"""split order_items.unit_price into quoted_price + confirmed_price (ADR-0007)

Revision ID: cc799d4e07c4
Revises: e491854cb645
Create Date: 2026-08-18 12:05:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cc799d4e07c4"
down_revision: str | None = "e491854cb645"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # order_items is empty in prod — Order creation has never been wired up
    # (see ADR-0007 "Последствия") — so this is a plain rename, no backfill.
    op.alter_column("order_items", "unit_price", new_column_name="quoted_price")
    op.add_column(
        "order_items",
        sa.Column("confirmed_price", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "confirmed_at")
    op.drop_column("order_items", "confirmed_price")
    op.alter_column("order_items", "quoted_price", new_column_name="unit_price")
