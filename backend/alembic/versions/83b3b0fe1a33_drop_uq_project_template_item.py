"""drop uq_project_template_item — allow duplicate materials in a template

Revision ID: 83b3b0fe1a33
Revises: 2d4335886fd3
Create Date: 2026-09-25 00:00:00.000000

ADR-0038: a material may now appear in a project template more than once
(each addition is an independent row); see the ADR for rationale.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "83b3b0fe1a33"
down_revision: str | None = "2d4335886fd3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_project_template_item", "project_template_items", type_="unique"
    )


def downgrade() -> None:
    # Restores the constraint shape only. If duplicate (template_id,
    # material_id) rows accumulated while this migration was applied, this
    # will fail until that data is resolved manually — same precedent as
    # migration 2d4335886fd3's lossy downgrade.
    op.create_unique_constraint(
        "uq_project_template_item",
        "project_template_items",
        ["template_id", "material_id"],
    )
