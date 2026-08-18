"""add manual override fields to allocation_lines (ADR-0006)

Revision ID: b2e5f8a1c3d7
Revises: a3f7c9d1e2b4
Create Date: 2026-08-18 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b2e5f8a1c3d7"
down_revision: str | None = "a3f7c9d1e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "allocation_lines",
        sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "allocation_lines",
        sa.Column("original_supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "allocation_lines",
        sa.Column("original_unit_price", sa.Numeric(12, 2), nullable=True),
    )
    op.create_foreign_key(
        "fk_allocation_lines_original_supplier_id_suppliers",
        "allocation_lines",
        "suppliers",
        ["original_supplier_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_allocation_lines_original_supplier_id_suppliers",
        "allocation_lines",
        type_="foreignkey",
    )
    op.drop_column("allocation_lines", "original_unit_price")
    op.drop_column("allocation_lines", "original_supplier_id")
    op.drop_column("allocation_lines", "overridden_at")
