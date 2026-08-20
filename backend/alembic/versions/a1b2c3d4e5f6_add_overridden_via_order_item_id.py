"""add overridden_via_order_item_id to allocation_lines (ADR-0014)

Revision ID: a1b2c3d4e5f6
Revises: 91375d2866f3
Create Date: 2026-08-20 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "91375d2866f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "allocation_lines",
        sa.Column(
            "overridden_via_order_item_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_allocation_lines_overridden_via_order_item_id_order_items",
        "allocation_lines",
        "order_items",
        ["overridden_via_order_item_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_allocation_lines_overridden_via_order_item_id_order_items",
        "allocation_lines",
        type_="foreignkey",
    )
    op.drop_column("allocation_lines", "overridden_via_order_item_id")
