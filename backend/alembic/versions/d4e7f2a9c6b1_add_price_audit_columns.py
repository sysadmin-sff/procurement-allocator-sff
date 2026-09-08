"""add created_by_user_id and source_order_item_id to prices (ADR-0030)

Revision ID: d4e7f2a9c6b1
Revises: 1be2571bb06f
Create Date: 2026-09-08 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d4e7f2a9c6b1"
down_revision: str | None = "1be2571bb06f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prices",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_prices_created_by_user_id_users",
        "prices",
        "users",
        ["created_by_user_id"],
        ["id"],
    )

    op.add_column(
        "prices",
        sa.Column("source_order_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_prices_source_order_item_id_order_items",
        "prices",
        "order_items",
        ["source_order_item_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_prices_source_order_item_id_order_items", "prices", type_="foreignkey"
    )
    op.drop_column("prices", "source_order_item_id")

    op.drop_constraint("fk_prices_created_by_user_id_users", "prices", type_="foreignkey")
    op.drop_column("prices", "created_by_user_id")
