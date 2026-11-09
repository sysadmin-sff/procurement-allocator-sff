"""Tests for the ADR-0042 migration (f41d3f445189): categories.display_order
backfilled by exact name match against the approved 8-category order, then
set NOT NULL.

Two layers:

- `compute_display_orders` (the pure name-set -> {name: order} lookup,
  extracted from upgrade() specifically so it's testable without a DB) is
  exercised directly with synthetic name sets for the unknown-name failure
  and missing-name warning paths -- no DB needed, no risk to real data.
- `upgrade()` itself is exercised once, end-to-end, against the categories
  table seeded with the 8 approved rows by a fixture, inside a transaction
  rolled back at teardown.
  Loaded by file path and run via a bound alembic Operations context on this
  test's own connection, rather than through the full `alembic.command`
  chain, for the same reason as
  tests/allocation/test_order_item_migration.py: walking the whole chain
  downgrades/upgrades every migration above and below this one, including
  ADR-0034's lossy Category downgrade, risking real dev-DB data.
"""

import uuid

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


APPROVED_NAMES = (
    "Screws",
    "Doors",
    "Roof panels",
    "Caulk",
    "Connectors",
    "Gutter",
    "Mesh",
    "Profil",
)


@pytest.fixture
def connection_with_approved_categories():
    """A connection whose categories table holds exactly the 8 approved rows.
    Everything is undone by the rollback at teardown."""
    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(text("TRUNCATE categories CASCADE"))
        for position, name in enumerate(APPROVED_NAMES):
            connection.execute(
                text(
                    """
                    INSERT INTO categories (id, name, sku_prefix, display_order)
                    VALUES (:id, :name, :prefix, :position)
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "name": name,
                    "prefix": name[:3].upper(),
                    "position": position,
                },
            )
        yield connection
    finally:
        transaction.rollback()
        connection.close()


def test_upgrade_backfills_the_real_categories_table(connection_with_approved_categories, caplog):
    """upgrade()'s add_column step isn't idempotent, so the column is dropped
    first, which puts the schema back to its pre-migration shape."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    connection = connection_with_approved_categories
    connection.execute(text("ALTER TABLE categories DROP COLUMN display_order"))

    with Operations.context(MigrationContext.configure(connection)):
        migration = _load_migration_module()
        with caplog.at_level("WARNING"):
            migration.upgrade()

    rows = connection.execute(text("SELECT name, display_order FROM categories")).fetchall()
    assert {row.name: row.display_order for row in rows} == {
        "Doors": 0,
        "Gutter": 1,
        "Caulk": 2,
        "Profil": 3,
        "Roof panels": 4,
        "Mesh": 5,
        "Connectors": 6,
        "Screws": 7,
    }
    assert not any("not found in categories table" in r.message for r in caplog.records)

    is_nullable = connection.execute(
        text(
            """
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'categories' AND column_name = 'display_order'
            """
        )
    ).scalar()
    assert is_nullable == "NO"
