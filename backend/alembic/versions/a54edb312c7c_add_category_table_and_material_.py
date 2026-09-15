"""add category table and material category_id

Revision ID: a54edb312c7c
Revises: a7c3e9f21b04
Create Date: 2026-09-16 01:20:50.731446

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a54edb312c7c"
down_revision: str | None = "a7c3e9f21b04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("sku_prefix", sa.String(length=10), nullable=False),
        sa.Column(
            "requires_single_supplier", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("next_sku_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_categories_name"),
        sa.UniqueConstraint("sku_prefix", name="uq_categories_sku_prefix"),
    )
    op.add_column(
        "materials",
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_materials_category_id_categories",
        "materials",
        "categories",
        ["category_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_materials_category_id_categories", "materials", type_="foreignkey")
    op.drop_column("materials", "category_id")
    op.drop_table("categories")
