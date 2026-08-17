"""cascade delete on supplier_material_aliases fks

Revision ID: 799b1a2dfae9
Revises: f78b06284148
Create Date: 2026-08-16 21:27:20.563608

"""
from collections.abc import Sequence

from alembic import op

revision: str = "799b1a2dfae9"
down_revision: str | None = "f78b06284148"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "supplier_material_aliases_supplier_id_fkey",
        "supplier_material_aliases",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "supplier_material_aliases_supplier_id_fkey",
        "supplier_material_aliases",
        "suppliers",
        ["supplier_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "supplier_material_aliases_material_id_fkey",
        "supplier_material_aliases",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "supplier_material_aliases_material_id_fkey",
        "supplier_material_aliases",
        "materials",
        ["material_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "supplier_material_aliases_material_id_fkey",
        "supplier_material_aliases",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "supplier_material_aliases_material_id_fkey",
        "supplier_material_aliases",
        "materials",
        ["material_id"],
        ["id"],
    )

    op.drop_constraint(
        "supplier_material_aliases_supplier_id_fkey",
        "supplier_material_aliases",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "supplier_material_aliases_supplier_id_fkey",
        "supplier_material_aliases",
        "suppliers",
        ["supplier_id"],
        ["id"],
    )
