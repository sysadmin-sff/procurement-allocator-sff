"""lightweight order item without material (ADR-0033)

Revision ID: a7c3e9f21b04
Revises: 3e8ec86bb865
Create Date: 2026-09-14 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c3e9f21b04"
down_revision: str | None = "3e8ec86bb865"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All existing rows have material_id filled and raw_description NULL —
    # they satisfy the CHECK constraint automatically, no backfill needed
    # (see ADR-0033 §1).
    op.alter_column("order_items", "material_id", nullable=True)
    op.add_column("order_items", sa.Column("raw_description", sa.String(500), nullable=True))
    op.create_check_constraint(
        "ck_order_items_material_xor_raw_description",
        "order_items",
        "(material_id IS NOT NULL) != (raw_description IS NOT NULL)",
    )


def downgrade() -> None:
    # Explicit refusal instead of silently dropping raw_description data —
    # see ADR-0033 §1 "Downgrade миграции — явный отказ".
    bind = op.get_bind()
    orphaned = bind.execute(
        sa.text("SELECT count(*) FROM order_items WHERE material_id IS NULL")
    ).scalar()
    if orphaned:
        raise RuntimeError(
            f"Cannot downgrade: {orphaned} order_items row(s) have "
            "material_id IS NULL (raw_description-only rows from "
            "ADR-0033). Resolve or delete them manually before "
            "downgrading — this migration will not silently drop data."
        )
    op.drop_constraint(
        "ck_order_items_material_xor_raw_description", "order_items", type_="check"
    )
    op.drop_column("order_items", "raw_description")
    op.alter_column("order_items", "material_id", nullable=False)
