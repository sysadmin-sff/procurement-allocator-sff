"""add received_quantity to order_items (ADR-0039)

Revision ID: 18f0d08c8c45
Revises: 83b3b0fe1a33
Create Date: 2026-09-29 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "18f0d08c8c45"
down_revision: str | None = "83b3b0fe1a33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("received_quantity", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "received_quantity")
