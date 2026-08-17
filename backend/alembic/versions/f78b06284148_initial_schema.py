"""initial schema

Revision ID: f78b06284148
Revises:
Create Date: 2026-08-16 02:35:21.843123

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f78b06284148"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("contacts", sa.String(1000)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("delivery_policy", sa.JSON, nullable=False),
    )

    op.create_table(
        "materials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("internal_sku", sa.String(100), nullable=False, unique=True),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100)),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("attributes", sa.JSON, nullable=False),
    )

    op.create_table(
        "supplier_material_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id"),
            nullable=False,
        ),
        sa.Column(
            "material_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("materials.id"),
            nullable=False,
        ),
        sa.Column("supplier_sku", sa.String(100)),
        sa.Column("supplier_raw_name", sa.String(255), nullable=False),
    )
    op.create_index(
        "ix_supplier_material_aliases_supplier_material",
        "supplier_material_aliases",
        ["supplier_id", "material_id"],
    )

    op.create_table(
        "price_list_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id"),
            nullable=False,
        ),
        sa.Column("file_ref", sa.String(500), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_review"),
        sa.Column("parsed_by_ai_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "price_list_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("price_list_imports.id"),
            nullable=False,
        ),
        sa.Column("supplier_raw_name", sa.String(255), nullable=False),
        sa.Column("supplier_sku", sa.String(100)),
        sa.Column(
            "matched_material_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("materials.id"),
        ),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("reasoning", sa.String(2000)),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("availability", sa.Integer),
        sa.Column("min_order_qty", sa.Integer),
        sa.Column("action", sa.String(20)),
    )
    op.create_index(
        "ix_price_list_entries_import_id", "price_list_entries", ["import_id"]
    )

    op.create_table(
        "prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "material_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("materials.id"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id"),
            nullable=False,
        ),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("availability", sa.Integer),
        sa.Column("min_order_qty", sa.Integer),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_to", sa.Date),
        sa.Column(
            "source_import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("price_list_imports.id"),
        ),
    )
    op.create_index(
        "ix_prices_material_supplier_valid_to",
        "prices",
        ["material_id", "supplier_id", "valid_to"],
    )

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255)),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
    )

    op.create_table(
        "project_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "material_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("materials.id"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer, nullable=False),
    )

    op.create_table(
        "allocation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("algorithm_version", sa.String(50)),
    )

    op.create_table(
        "allocation_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "allocation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("allocation_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "material_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("materials.id"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
    )

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("delivery_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("file_ref", sa.String(500)),
    )

    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id"),
            nullable=False,
        ),
        sa.Column(
            "material_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("materials.id"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("allocation_lines")
    op.drop_table("allocation_runs")
    op.drop_table("project_items")
    op.drop_table("projects")
    op.drop_table("prices")
    op.drop_table("price_list_entries")
    op.drop_table("price_list_imports")
    op.drop_table("supplier_material_aliases")
    op.drop_table("materials")
    op.drop_table("suppliers")
