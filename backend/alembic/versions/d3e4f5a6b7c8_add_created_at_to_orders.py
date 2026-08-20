"""add created_at to orders (ADR-0016 §3)

Revision ID: d3e4f5a6b7c8
Revises: a1b2c3d4e5f6
Create Date: 2026-08-20 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # clock_timestamp(), not now() — same reasoning as
    # a3f7c9d1e2b4_add_created_at_to_projects: now() is frozen at
    # transaction start, so two Orders inserted in the same transaction
    # would get an identical created_at, which ADR-0016 §3 relies on being
    # strictly ordered to pick "the latest Order containing this material".
    op.add_column(
        "orders",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "created_at")
