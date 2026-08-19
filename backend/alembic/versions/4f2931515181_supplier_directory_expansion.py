"""supplier directory expansion: offices, contacts, supplier fields (ADR-0010)

Revision ID: 4f2931515181
Revises: 596e12600468
Create Date: 2026-08-19 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "4f2931515181"
down_revision: str | None = "596e12600468"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("suppliers", sa.Column("website", sa.String(500), nullable=True))
    op.add_column("suppliers", sa.Column("region", sa.String(255), nullable=True))
    op.add_column("suppliers", sa.Column("catalog_link", sa.String(500), nullable=True))
    op.add_column("suppliers", sa.Column("status", sa.String(255), nullable=True))
    op.add_column("suppliers", sa.Column("payment_terms", sa.String(100), nullable=True))
    op.add_column("suppliers", sa.Column("portal_url", sa.String(500), nullable=True))
    op.add_column("suppliers", sa.Column("comments", sa.Text(), nullable=True))

    op.create_table(
        "offices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("region", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "supplier_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("office_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("supplier_contacts")
    op.drop_table("offices")
    op.drop_column("suppliers", "comments")
    op.drop_column("suppliers", "portal_url")
    op.drop_column("suppliers", "payment_terms")
    op.drop_column("suppliers", "status")
    op.drop_column("suppliers", "catalog_link")
    op.drop_column("suppliers", "region")
    op.drop_column("suppliers", "website")
