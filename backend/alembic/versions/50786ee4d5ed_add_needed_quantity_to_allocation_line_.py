"""add needed_quantity to allocation_line and order_item

Revision ID: 50786ee4d5ed
Revises: c7f2a91b4e0d
Create Date: 2026-10-14 18:03:31.878354

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "50786ee4d5ed"
down_revision: str | None = "c7f2a91b4e0d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("allocation_lines", sa.Column("needed_quantity", sa.Integer(), nullable=True))
    op.add_column("order_items", sa.Column("needed_quantity", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("order_items", "needed_quantity")
    op.drop_column("allocation_lines", "needed_quantity")
