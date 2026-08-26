"""add audit user fk columns

Revision ID: 1d82548b7a2c
Revises: 18515d737158
Create Date: 2026-08-26 20:21:20.106782

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "1d82548b7a2c"
down_revision: str | None = "18515d737158"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("projects", "created_by")
    op.add_column(
        "projects",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_projects_created_by_user_id_users",
        "projects",
        "users",
        ["created_by_user_id"],
        ["id"],
    )

    op.add_column(
        "orders",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_orders_created_by_user_id_users",
        "orders",
        "users",
        ["created_by_user_id"],
        ["id"],
    )

    op.add_column(
        "purchase_records",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_purchase_records_created_by_user_id_users",
        "purchase_records",
        "users",
        ["created_by_user_id"],
        ["id"],
    )

    op.add_column(
        "allocation_lines",
        sa.Column("overridden_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_allocation_lines_overridden_by_user_id_users",
        "allocation_lines",
        "users",
        ["overridden_by_user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_allocation_lines_overridden_by_user_id_users", "allocation_lines", type_="foreignkey"
    )
    op.drop_column("allocation_lines", "overridden_by_user_id")

    op.drop_constraint(
        "fk_purchase_records_created_by_user_id_users", "purchase_records", type_="foreignkey"
    )
    op.drop_column("purchase_records", "created_by_user_id")

    op.drop_constraint("fk_orders_created_by_user_id_users", "orders", type_="foreignkey")
    op.drop_column("orders", "created_by_user_id")

    op.drop_constraint(
        "fk_projects_created_by_user_id_users", "projects", type_="foreignkey"
    )
    op.drop_column("projects", "created_by_user_id")
    op.add_column("projects", sa.Column("created_by", sa.String(length=255), nullable=True))
