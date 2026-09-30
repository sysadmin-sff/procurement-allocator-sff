"""add is_active_for_allocation to suppliers

Revision ID: e2934e988fd6
Revises: 18f0d08c8c45
Create Date: 2026-09-30 21:24:53.096523

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2934e988fd6"
down_revision: str | None = "18f0d08c8c45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "suppliers",
        sa.Column(
            "is_active_for_allocation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("suppliers", "is_active_for_allocation")
