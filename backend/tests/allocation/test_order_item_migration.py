"""Tests for the ADR-0033 migration (a7c3e9f21b04): order_items.material_id
becomes nullable, new raw_description column, CHECK constraint
ck_order_items_material_xor_raw_description, and the explicit downgrade
guard against silently dropping raw_description-only rows.

These run the migration's DB-level guarantees directly (raw INSERT, real
alembic downgrade/upgrade), not through the ORM or the API — the whole point
of a CHECK constraint is that it holds even when application code is
bypassed.
"""

import logging
import uuid

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.database import SessionLocal
from app.models import Order, OrderItem, Project, Supplier


@pytest.fixture(autouse=True)
def _restore_logger_state():
    """alembic/env.py calls logging.config.fileConfig(), which defaults to
    disable_existing_loggers=True — every command.downgrade/upgrade call
    below disables every logger not named in alembic.ini's [loggers]
    section (root/sqlalchemy/alembic), process-wide, for the rest of the
    pytest session. Left unguarded, this silently breaks caplog-based
    assertions in unrelated test files that happen to run afterward (e.g.
    tests/auth/test_oauth_flow.py) — found by comparing `git stash`
    before/after test-name sets, not by reasoning about it in advance.
    Snapshot/restore each logger's .disabled flag around this module's
    tests so the leak doesn't escape this file."""
    manager = logging.Logger.manager
    before = {
        name: logger.disabled
        for name, logger in manager.loggerDict.items()
        if hasattr(logger, "disabled")
    }
    yield
    for name, logger in manager.loggerDict.items():
        if hasattr(logger, "disabled"):
            logger.disabled = before.get(name, False)


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


def _alembic_config() -> Config:
    return Config("alembic.ini")


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

    cfg = _alembic_config()
    with pytest.raises(RuntimeError, match="material_id IS NULL"):
        command.downgrade(cfg, "-1")

    # Confirm we're still at head — the guard raised before any DDL ran.
    command.upgrade(cfg, "head")


def test_downgrade_succeeds_with_no_light_rows(db_session):
    """Regression: downgrade must still work cleanly when the table has no
    raw_description-only rows at all."""
    cfg = _alembic_config()
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
