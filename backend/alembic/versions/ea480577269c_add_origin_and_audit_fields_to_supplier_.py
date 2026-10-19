"""add origin and audit fields to supplier_material_aliases

Revision ID: ea480577269c
Revises: 50786ee4d5ed
Create Date: 2026-10-19 19:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "ea480577269c"
down_revision: str | None = "50786ee4d5ed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "supplier_material_aliases",
        sa.Column("origin", sa.String(length=20), nullable=False, server_default="price_import"),
    )
    op.add_column(
        "supplier_material_aliases",
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "supplier_material_aliases",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("supplier_material_aliases", "created_at")
    op.drop_column("supplier_material_aliases", "created_by_user_id")
    op.drop_column("supplier_material_aliases", "origin")
