"""measurements reference rows: missing_since instead of deletion (ADR-0051 §4)

Revision ID: f2b9d6a41c83
Revises: c4a7e19d2b60
Create Date: 2026-11-10 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2b9d6a41c83"
down_revision: str | None = "c4a7e19d2b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "measurements_pipeline_statuses",
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "measurements_amo_users",
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("measurements_amo_users", "missing_since")
    op.drop_column("measurements_pipeline_statuses", "missing_since")
