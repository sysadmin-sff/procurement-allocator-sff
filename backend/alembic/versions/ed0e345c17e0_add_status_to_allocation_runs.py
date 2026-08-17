"""add status to allocation_runs, with conditional backfill (ADR-0003)

Revision ID: ed0e345c17e0
Revises: d1a2f3c4b5e6
Create Date: 2026-08-17 22:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ed0e345c17e0"
down_revision: str | None = "d1a2f3c4b5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("allocation_runs", sa.Column("status", sa.String(length=20), nullable=True))

    # Do NOT default every existing row to 'ok' — that would encode the exact
    # bug ADR-0003 fixes (a pre-fix run_allocation() could already have
    # produced a "successful" AllocationRun with zero lines when the ILP
    # model was infeasible). Backfill conditionally: a run with no
    # allocation_lines and no orphaned_materials could only exist through
    # that bug (EmptyProjectError blocks the zero-ProjectItem case before an
    # AllocationRun is ever created), so it is reclassified as 'infeasible'.
    # Compared as ::text, not ::json — plain Postgres `json` (unlike `jsonb`)
    # has no equality operator, only `jsonb` does.
    op.execute(
        """
        UPDATE allocation_runs
        SET status = CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM allocation_lines
                WHERE allocation_lines.allocation_run_id = allocation_runs.id
            )
            AND orphaned_materials::text = '[]'
            THEN 'infeasible'
            ELSE 'ok'
        END
        """
    )

    op.alter_column("allocation_runs", "status", nullable=False)


def downgrade() -> None:
    op.drop_column("allocation_runs", "status")
