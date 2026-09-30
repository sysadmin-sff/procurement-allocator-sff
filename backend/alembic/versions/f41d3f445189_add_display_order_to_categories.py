"""add display_order to categories

ADR-0042: fixed, admin-controlled ordering for the 8 existing categories,
used everywhere categories are listed/grouped. Column is added nullable,
backfilled by exact `name` match against the approved order below, then set
NOT NULL -- mirrors the two-phase shape of a54edb312c7c/2d4335886fd3.

Revision ID: f41d3f445189
Revises: e2934e988fd6
Create Date: 2026-09-30 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f41d3f445189"
down_revision: str | None = "e2934e988fd6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Approved order (ADR-0042) -- matched against Category.name byte-for-byte,
# case and whitespace included. Not derived from any existing code constant
# (e.g. CATEGORY_SKU_PREFIX's iteration order) on purpose -- this list is
# itself the source of truth for display order, independent of any other
# list's incidental ordering.
CATEGORY_DISPLAY_ORDER: dict[str, int] = {
    "Doors": 0,
    "Gutter": 1,
    "Caulk": 2,
    "Profil": 3,
    "Roof panels": 4,
    "Mesh": 5,
    "Connectors": 6,
    "Screws": 7,
}


def compute_display_orders(found_names: set[str]) -> dict[str, int]:
    """Pure name -> display_order lookup, separated from DB I/O so the
    unknown-name guard and the missing-name warning can be unit tested
    against synthetic name sets, without needing a real (or temp) categories
    table -- see tests/category/test_display_order_migration.py.

    Raises RuntimeError if `found_names` contains anything outside
    CATEGORY_DISPLAY_ORDER; logs a WARNING (does not raise) for approved
    names with no matching row -- see ADR-0042 п.2."""
    known_names = set(CATEGORY_DISPLAY_ORDER)

    unknown_names = sorted(found_names - known_names)
    if unknown_names:
        raise RuntimeError(
            "categories.display_order backfill (ADR-0042): found category "
            f"name(s) not in the approved order list: {unknown_names!r}. "
            "This is either a typo/casing/whitespace mismatch against the "
            "approved list in this migration, or a category added after "
            "ADR-0042 was written -- add it to CATEGORY_DISPLAY_ORDER in "
            "this migration (with a follow-up ADR note) before re-running, "
            "rather than silently leaving its display_order unset."
        )

    missing_names = sorted(known_names - found_names)
    if missing_names:
        import logging

        logging.getLogger("alembic.runtime.migration").warning(
            "categories.display_order backfill (ADR-0042): approved category "
            "name(s) not found in categories table, nothing to backfill for "
            "them: %r",
            missing_names,
        )

    return dict(CATEGORY_DISPLAY_ORDER)


def upgrade() -> None:
    op.add_column("categories", sa.Column("display_order", sa.Integer(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, name FROM categories")).fetchall()

    display_orders = compute_display_orders({row.name for row in rows})

    for row in rows:
        bind.execute(
            sa.text("UPDATE categories SET display_order = :order WHERE id = :id"),
            {"order": display_orders[row.name], "id": row.id},
        )

    op.alter_column("categories", "display_order", nullable=False)


def downgrade() -> None:
    op.drop_column("categories", "display_order")
