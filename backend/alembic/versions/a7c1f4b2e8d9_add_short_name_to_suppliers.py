"""add short_name to suppliers (ADR-0017)

Revision ID: a7c1f4b2e8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-08-25 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c1f4b2e8d9"
down_revision: str | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("suppliers", sa.Column("short_name", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("suppliers", "short_name")
