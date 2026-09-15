"""Tests for the ADR-0033 migration (a7c3e9f21b04): order_items.material_id
becomes nullable, new raw_description column, CHECK constraint
ck_order_items_material_xor_raw_description, and the explicit downgrade
guard against silently dropping raw_description-only rows.

These run the migration's DB-level guarantees directly (raw INSERT), not
through the ORM or the API — the whole point of a CHECK constraint is that
it holds even when application code is bypassed.

The two downgrade-guard tests invoke a7c3e9f21b04's downgrade()/upgrade()
module functions directly (via a bound alembic Operations context on this
test's own connection, inside a transaction rolled back at teardown) rather
than running `alembic downgrade`/`upgrade` through the whole migration
chain via `alembic.command`. See ADR-0034 discovery: once migrations exist
above a7c3e9f21b04, a live `command.downgrade` to its parent revision walks
DOWN THROUGH every newer migration first — including ADR-0034's two-phase
Category migration, whose downgrade is deliberately lossy (documented in
that migration itself) and cannot be un-done by a subsequent
`command.upgrade(cfg, "head")` without re-running an external backfill
script. A prior version of this test suite used `command.downgrade`/
`command.upgrade` and, run against a live dev DB, silently destroyed real
Category data this way. Invoking the migration's own functions in isolation
tests exactly the guard this file is about, with no dependency on how many
migrations exist above or below it, and no risk to any other migration's
data."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal, engine
from app.models import Order, OrderItem, Project, Supplier


@pytest.fixture
def db_session():
    session = SessionLocal()
    project_ids: list = []
    supplier_ids: list = []

    try:
        yield session, project_ids, supplier_ids
    finally:
        session.rollback()
        for project_id in project_ids:
            order_ids = [
                o.id for o in session.query(Order).filter_by(project_id=project_id).all()
            ]
            if order_ids:
                session.query(OrderItem).filter(OrderItem.order_id.in_(order_ids)).delete(
                    synchronize_session=False
                )
                session.query(Order).filter(Order.id.in_(order_ids)).delete(
                    synchronize_session=False
                )
            session.query(Project).filter_by(id=project_id).delete(synchronize_session=False)
        if supplier_ids:
            session.query(Supplier).filter(Supplier.id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
        session.commit()
        session.close()


@pytest.fixture
def make_order_shell(db_session):
    """A minimal Order to hang order_items rows off of — no materials, no
    allocation run, just enough parent rows for the FK/CHECK tests below."""
    session, project_ids, supplier_ids = db_session

    def _make():
        supplier = Supplier(
            name="Migration Test Supplier",
            currency="USD",
            delivery_policy={
                "flat_fee": 0.0,
                "free_shipping_threshold": 0.0,
                "per_order_min_amount": 0.0,
                "lead_time_days": 1,
            },
        )
        session.add(supplier)
        session.flush()
        supplier_ids.append(supplier.id)

        project = Project(title="Migration Test Project", status="draft")
        session.add(project)
        session.flush()
        project_ids.append(project.id)

        order = Order(
            project_id=project.id,
            supplier_id=supplier.id,
            status="draft",
            total_amount=0,
            delivery_fee=0,
        )
        session.add(order)
        session.flush()
        return order

    return _make


def test_check_constraint_rejects_both_fields_filled(db_session, make_order_shell):
    session, *_ = db_session
    order = make_order_shell()

    with pytest.raises(IntegrityError, match="ck_order_items_material_xor_raw_description"):
        session.execute(
            text(
                """
                INSERT INTO order_items
                    (id, order_id, material_id, raw_description, quantity, quoted_price)
                VALUES
                    (:id, :order_id, :material_id, :raw_description, :quantity, :quoted_price)
                """
            ),
            {
                "id": uuid.uuid4(),
                "order_id": order.id,
                "material_id": uuid.uuid4(),
                "raw_description": "both fields filled",
                "quantity": 1,
                "quoted_price": 1.00,
            },
        )
    session.rollback()


def test_check_constraint_rejects_neither_field_filled(db_session, make_order_shell):
    session, *_ = db_session
    order = make_order_shell()

    with pytest.raises(IntegrityError, match="ck_order_items_material_xor_raw_description"):
        session.execute(
            text(
                """
                INSERT INTO order_items
                    (id, order_id, material_id, raw_description, quantity, quoted_price)
                VALUES
                    (:id, :order_id, NULL, NULL, :quantity, :quoted_price)
                """
            ),
            {
                "id": uuid.uuid4(),
                "order_id": order.id,
                "quantity": 1,
                "quoted_price": 1.00,
            },
        )
    session.rollback()


def _load_migration_module():
    """Imports the a7c3e9f21b04 migration file as a plain Python module (by
    file path, since alembic/versions/*.py aren't a normal package) so its
    upgrade()/downgrade() functions can be called directly, without going
    through `alembic.command` and the full revision chain. See module
    docstring for why this replaced the previous command.downgrade/upgrade
    approach."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "a7c3e9f21b04_lightweight_order_item_without_.py"
    )
    spec = importlib.util.spec_from_file_location("a7c3e9f21b04_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_downgrade_fails_when_light_row_exists(db_session, make_order_shell):
    session, *_ = db_session
    order = make_order_shell()
    session.add(
        OrderItem(
            order_id=order.id,
            material_id=None,
            raw_description="Something the supplier sent that isn't in our catalog",
            quantity=1,
            quoted_price=9.99,
        )
    )
    session.commit()

    migration = _load_migration_module()
    connection = engine.connect()
    transaction = connection.begin()
    try:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        context = MigrationContext.configure(connection)
        with Operations.context(context):
            with pytest.raises(RuntimeError, match="material_id IS NULL"):
                migration.downgrade()
    finally:
        # Roll back regardless of outcome -- this test only verifies the
        # guard raises before any DDL runs, it never intends to leave the
        # schema downgraded (real downgrades to this revision are covered
        # by test_downgrade_succeeds_with_no_light_rows).
        transaction.rollback()
        connection.close()


def test_downgrade_succeeds_with_no_light_rows(db_session):
    """Regression: downgrade must still work cleanly (no RuntimeError) when
    the table has no raw_description-only rows at all -- run against a
    transaction rolled back at the end, so this never leaves the real schema
    downgraded (that would desync it from the ORM models used by every other
    test in the suite)."""
    migration = _load_migration_module()
    connection = engine.connect()
    transaction = connection.begin()
    try:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.downgrade()
            migration.upgrade()
    finally:
        transaction.rollback()
        connection.close()
