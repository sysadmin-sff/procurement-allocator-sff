"""add tax_amount to orders

Revision ID: 1be2571bb06f
Revises: 5eeff6d921a9
Create Date: 2026-09-05 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "1be2571bb06f"
down_revision: str | None = "5eeff6d921a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "tax_amount")
