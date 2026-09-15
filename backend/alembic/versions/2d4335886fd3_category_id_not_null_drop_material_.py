"""category_id not null, drop material category string column

Revision ID: 2d4335886fd3
Revises: a54edb312c7c
Create Date: 2026-09-16 01:59:28.568619

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2d4335886fd3"
down_revision: str | None = "a54edb312c7c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("materials", "category_id", nullable=False)
    op.drop_column("materials", "category")


def downgrade() -> None:
    # Lossy: restores the column shape only, not the original string values
    # (same precedent as migration 1d82548b7a2c's created_by column restore).
    op.add_column("materials", sa.Column("category", sa.String(length=100), nullable=True))
    op.alter_column("materials", "category_id", nullable=True)
