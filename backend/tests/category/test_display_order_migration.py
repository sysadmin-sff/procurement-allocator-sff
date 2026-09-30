"""Tests for the ADR-0042 migration (f41d3f445189): categories.display_order
backfilled by exact name match against the approved 8-category order, then
set NOT NULL.

Two layers:

- `compute_display_orders` (the pure name-set -> {name: order} lookup,
  extracted from upgrade() specifically so it's testable without a DB) is
  exercised directly with synthetic name sets for the unknown-name failure
  and missing-name warning paths -- no DB needed, no risk to real data.
- `upgrade()` itself is exercised once, end-to-end, against the real
  categories table -- which already holds exactly the 8 approved rows after
  `alembic upgrade head` -- inside a transaction rolled back at teardown.
  Loaded by file path and run via a bound alembic Operations context on this
  test's own connection, rather than through the full `alembic.command`
  chain, for the same reason as
  tests/allocation/test_order_item_migration.py: walking the whole chain
  downgrades/upgrades every migration above and below this one, including
  ADR-0034's lossy Category downgrade, risking real dev-DB data.
"""

import pytest
from sqlalchemy import text

from app.core.database import engine


def _load_migration_module():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "f41d3f445189_add_display_order_to_categories.py"
    )
    spec = importlib.util.spec_from_file_location("f41d3f445189_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- compute_display_orders: pure unit tests, no DB ---


def test_compute_display_orders_returns_approved_order_for_all_eight_names():
    migration = _load_migration_module()

    result = migration.compute_display_orders(
        {"Screws", "Doors", "Roof panels", "Caulk", "Connectors", "Gutter", "Mesh", "Profil"}
    )

    assert result == {
        "Doors": 0,
        "Gutter": 1,
        "Caulk": 2,
        "Profil": 3,
        "Roof panels": 4,
        "Mesh": 5,
        "Connectors": 6,
        "Screws": 7,
    }


def test_compute_display_orders_raises_on_unknown_name():
    migration = _load_migration_module()

    with pytest.raises(RuntimeError, match=r"Widgets"):
        migration.compute_display_orders({"Doors", "Gutter", "Widgets"})


def test_compute_display_orders_warns_but_succeeds_when_approved_name_missing(caplog):
    migration = _load_migration_module()

    with caplog.at_level("WARNING"):
        result = migration.compute_display_orders({"Doors", "Mesh"})

    # Still returns the full approved mapping -- callers key into it by the
    # rows they actually have, so unused entries for missing names are
    # harmless (see upgrade()'s `display_orders[row.name]` lookup).
    assert result["Doors"] == 0
    assert result["Mesh"] == 5
    assert any("not found in categories table" in r.message for r in caplog.records)
    assert any("Gutter" in r.message for r in caplog.records)


# --- upgrade(): one end-to-end test against the real schema ---


def test_upgrade_backfills_the_real_categories_table(caplog):
    """The real dev DB already has exactly the 8 approved categories (from
    the actual `alembic upgrade head` run). To re-run upgrade()'s own
    add_column step faithfully (it isn't idempotent), this first drops the
    column inside a rolled-back transaction -- putting the schema back to
    exactly its pre-migration shape -- then invokes the real upgrade(), all
    without ever inserting/deleting a categories row (which would risk
    uq_categories_name collisions or the materials FK against real data)."""
    connection = engine.connect()
    transaction = connection.begin()
    try:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        connection.execute(text("ALTER TABLE categories DROP COLUMN display_order"))

        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration = _load_migration_module()
            with caplog.at_level("WARNING"):
                migration.upgrade()

        rows = connection.execute(text("SELECT name, display_order FROM categories")).fetchall()
        result = {row.name: row.display_order for row in rows}
        assert result == {
            "Doors": 0,
            "Gutter": 1,
            "Caulk": 2,
            "Profil": 3,
            "Roof panels": 4,
            "Mesh": 5,
            "Connectors": 6,
            "Screws": 7,
        }
        # All 8 approved names present in real data -- no missing-name warning.
        assert not any("not found in categories table" in r.message for r in caplog.records)

        not_null = connection.execute(
            text(
                """
                SELECT is_nullable FROM information_schema.columns
                WHERE table_name = 'categories' AND column_name = 'display_order'
                """
            )
        ).scalar()
        assert not_null == "NO"
    finally:
        transaction.rollback()
        connection.close()
