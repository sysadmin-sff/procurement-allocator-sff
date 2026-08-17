"""add created_at to projects

Revision ID: a3f7c9d1e2b4
Revises: ed0e345c17e0
Create Date: 2026-08-17 23:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3f7c9d1e2b4"
down_revision: str | None = "ed0e345c17e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # clock_timestamp(), not now(): now() is frozen at transaction start, so
    # rows inserted in the same transaction (e.g. test fixtures creating two
    # projects back to back) would get an identical created_at and make
    # ORDER BY created_at DESC ambiguous between them.
    op.add_column(
        "projects",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "created_at")
