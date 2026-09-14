"""add composite index (material_id, supplier_id, valid_to) on prices

Revision ID: 3e8ec86bb865
Revises: 5e49cad05696
Create Date: 2026-09-14 16:31:22.021267

"""
from collections.abc import Sequence

from alembic import op

revision: str = "3e8ec86bb865"
down_revision: str | None = "5e49cad05696"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Distinct from the existing partial unique index
    # ux_prices_active_material_supplier (material_id, supplier_id WHERE
    # valid_to IS NULL, see d1a2f3c4b5e6): this one is a plain composite
    # index covering the same three columns but not restricted to active
    # rows, so it also serves list_prices()-style filters that don't limit
    # to valid_to IS NULL. See docs/known-issues.md.
    op.create_index(
        "ix_prices_material_supplier_valid_to",
        "prices",
        ["material_id", "supplier_id", "valid_to"],
    )


def downgrade() -> None:
    op.drop_index("ix_prices_material_supplier_valid_to", table_name="prices")
