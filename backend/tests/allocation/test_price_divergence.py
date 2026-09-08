"""Tests for PriceDivergence detection in set_order_item_fields — ADR-0030
п.1/п.2. Trigger is confirmed_price only (never received_price/target_price);
three cases: match (None), active price differs ("update"), no active price
at all ("create")."""

from app.allocation.order_service import (
    PriceDivergence,
    create_orders_for_run,
    set_order_item_fields,
)
from app.allocation.service import run_allocation
from app.models import Price


def _make_order_item(session, make_supplier, make_material, make_price, make_project):
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    return orders[0], orders[0].items[0], supplier, material


def test_confirmed_price_matching_active_price_returns_no_divergence(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )

    _, divergence = set_order_item_fields(session, order.id, item.id, confirmed_price=5.00)

    assert divergence is None


def test_confirmed_price_differing_from_active_price_returns_update_divergence(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )

    _, divergence = set_order_item_fields(session, order.id, item.id, confirmed_price=6.50)

    assert isinstance(divergence, PriceDivergence)
    assert divergence.action == "update"
    assert divergence.order_item_id == item.id
    assert divergence.material_id == material.id
    assert divergence.supplier_id == supplier.id
    assert divergence.current_price == 5.00
    assert divergence.confirmed_price == 6.50


def test_confirmed_price_with_no_active_price_returns_create_divergence(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Case (в): the order item's material/supplier pair has no active
    Price at all -- simulated by deleting the Price after the Order was
    created from it (ADR-0030 п.2's "deleted historical" example)."""
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )
    session.query(Price).filter_by(material_id=material.id, supplier_id=supplier.id).delete()
    session.commit()

    _, divergence = set_order_item_fields(session, order.id, item.id, confirmed_price=7.00)

    assert isinstance(divergence, PriceDivergence)
    assert divergence.action == "create"
    assert divergence.order_item_id == item.id
    assert divergence.material_id == material.id
    assert divergence.supplier_id == supplier.id
    assert divergence.current_price is None
    assert divergence.confirmed_price == 7.00


def test_setting_received_price_does_not_produce_divergence(
    db_session, make_supplier, make_material, make_price, make_project
):
    """received_price is explicitly not a trigger — ADR-0030 п.1."""
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )

    _, divergence = set_order_item_fields(session, order.id, item.id, received_price=9.99)

    assert divergence is None


def test_setting_target_price_does_not_produce_divergence(
    db_session, make_supplier, make_material, make_price, make_project
):
    """target_price is explicitly not a trigger — ADR-0030 п.1."""
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )

    _, divergence = set_order_item_fields(session, order.id, item.id, target_price=3.00)

    assert divergence is None


def test_omitting_confirmed_price_from_patch_produces_no_divergence(
    db_session, make_supplier, make_material, make_price, make_project
):
    """A PATCH that doesn't touch confirmed_price at all (e.g. only
    declined=True) must not produce a divergence, even if confirmed_price
    was set to a diverging value on a prior call."""
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )
    set_order_item_fields(session, order.id, item.id, confirmed_price=6.50)

    _, divergence = set_order_item_fields(
        session, order.id, item.id, declined=True, decline_reason="test"
    )

    assert divergence is None


def test_clearing_confirmed_price_to_none_produces_no_divergence(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Explicitly clearing confirmed_price (PATCH {confirmed_price: null})
    cannot "propose" updating Price to a None value — ADR-0030 п.2."""
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )
    set_order_item_fields(session, order.id, item.id, confirmed_price=6.50)

    _, divergence = set_order_item_fields(session, order.id, item.id, confirmed_price=None)

    assert divergence is None


def test_set_order_item_fields_still_returns_the_order_item(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Regression: the first tuple element must still be the OrderItem with
    the write applied, same as the old single-value return."""
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )

    updated_item, _ = set_order_item_fields(session, order.id, item.id, confirmed_price=6.50)

    assert updated_item.id == item.id
    assert float(updated_item.confirmed_price) == 6.50
