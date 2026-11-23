"""measurements leads: snapshot of the amo field Structure Cost $ (ADR-0053, 2026-11-23 change)

Revision ID: c7e2a9d40b15
Revises: b5d3e8a17f42
Create Date: 2026-11-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7e2a9d40b15"
down_revision: str | None = "b5d3e8a17f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "measurements_leads",
        sa.Column("structure_cost", sa.Numeric(precision=12, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("measurements_leads", "structure_cost")
