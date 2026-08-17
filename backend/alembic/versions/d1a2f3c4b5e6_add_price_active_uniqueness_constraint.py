"""add active-price uniqueness and date-order constraints to prices

Revision ID: d1a2f3c4b5e6
Revises: cbadcd5a2be0
Create Date: 2026-08-17 21:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "d1a2f3c4b5e6"
down_revision: str | None = "cbadcd5a2be0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ux_prices_active_material_supplier",
        "prices",
        ["material_id", "supplier_id"],
        unique=True,
        postgresql_where="valid_to IS NULL",
    )
    op.create_check_constraint(
        "ck_prices_valid_to_after_valid_from",
        "prices",
        "valid_to IS NULL OR valid_to >= valid_from",
    )


def downgrade() -> None:
    op.drop_constraint("ck_prices_valid_to_after_valid_from", "prices", type_="check")
    op.drop_index("ux_prices_active_material_supplier", table_name="prices")
