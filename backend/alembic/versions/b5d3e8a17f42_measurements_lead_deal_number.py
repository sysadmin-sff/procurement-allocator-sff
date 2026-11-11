"""measurements leads: snapshot of the amo field Deal Number (ADR-0053, 2026-11-11 change)

Revision ID: b5d3e8a17f42
Revises: a83d51c07e94
Create Date: 2026-11-11 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5d3e8a17f42"
down_revision: str | None = "a83d51c07e94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "measurements_leads",
        sa.Column("deal_number", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("measurements_leads", "deal_number")
