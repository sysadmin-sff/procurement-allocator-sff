"""add project_templates and project_template_items

Revision ID: 5e49cad05696
Revises: ff93f1837dbf
Create Date: 2026-09-14 02:42:08.621338

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5e49cad05696"
down_revision: str | None = "ff93f1837dbf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_templates_name", "project_templates", ["name"], unique=True
    )

    op.create_table(
        "project_template_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("material_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["project_templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id", "material_id", name="uq_project_template_item"
        ),
    )


def downgrade() -> None:
    op.drop_table("project_template_items")
    op.drop_index("ix_project_templates_name", table_name="project_templates")
    op.drop_table("project_templates")
