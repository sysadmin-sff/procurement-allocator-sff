"""add color_options/color_fragment to materials, color_choice to projects

Revision ID: ff93f1837dbf
Revises: d4e7f2a9c6b1
Create Date: 2026-09-09 00:01:57.980027

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ff93f1837dbf"
down_revision: str | None = "d4e7f2a9c6b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("materials", sa.Column("color_options", sa.JSON(), nullable=True))
    op.add_column("materials", sa.Column("color_fragment", sa.String(length=50), nullable=True))
    op.add_column("projects", sa.Column("color_choice", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "color_choice")
    op.drop_column("materials", "color_fragment")
    op.drop_column("materials", "color_options")
