"""backfill Project.status from existing AllocationRun/Order data (ADR-0011)

Revision ID: b15597e509ec
Revises: 4f2931515181
Create Date: 2026-08-19 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "b15597e509ec"
down_revision: str | None = "4f2931515181"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rule must match app.allocation.service.run_allocation() /
    # app.allocation.order_service.create_orders_for_run() exactly (ADR-0011 §6):
    # has an Order -> "ordered"; else has an AllocationRun with status="ok" ->
    # "calculated"; else leave as "draft" (already the default, untouched).
    op.execute(
        """
        UPDATE projects
        SET status = 'calculated'
        WHERE status = 'draft'
          AND EXISTS (
              SELECT 1 FROM allocation_runs
              WHERE allocation_runs.project_id = projects.id
                AND allocation_runs.status = 'ok'
          )
        """
    )
    op.execute(
        """
        UPDATE projects
        SET status = 'ordered'
        WHERE EXISTS (
            SELECT 1 FROM orders
            WHERE orders.project_id = projects.id
        )
        """
    )


def downgrade() -> None:
    # Data migration — no reliable inverse (we can't tell which projects were
    # genuinely "draft" before vs. backfilled). Left as a no-op, matching how
    # data-only corrections in this project are not designed to be reversible
    # (there is no prior precedent for a data-migration downgrade in
    # backend/alembic/versions/ to follow instead).
    pass
