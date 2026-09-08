"""Tests for confirm_price_updates — ADR-0030 п.4.3. Batch confirmation of
Price updates proposed by PriceDivergence during a batch confirmed_price
application session. Revalidates each row against current state (does not
trust client-shown current_price), commits per-row independently (one
failing row does not roll back or block the rest), and calls version_price
with created_by_user_id/source_order_item_id set."""

from app.allocation.order_service import (
    confirm_price_updates,
    create_orders_for_run,
    set_order_item_fields,
)
from app.allocation.service import run_allocation
from app.models import Price

_user_email_counter = [0]


def _unique_user(make_user):
    _user_email_counter[0] += 1
    return make_user(email=f"confirm-price-user{_user_email_counter[0]}@screen-factory-florida.com")


def _make_order_item(session, make_supplier, make_material, make_price, make_project):
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    return orders[0], orders[0].items[0], supplier, material


def test_confirm_price_updates_applies_update_and_sets_audit_columns(
    db_session, make_supplier, make_material, make_price, make_project, make_user
):
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )
    set_order_item_fields(session, order.id, item.id, confirmed_price=6.50)
    user = _unique_user(make_user)

    results = confirm_price_updates(
        session,
        order_id=order.id,
        selections=[{"order_item_id": item.id, "apply": True}],
        current_user_id=user.id,
    )

    assert len(results) == 1
    result = results[0]
    assert result.applied is True
    assert result.action == "update"
    assert result.error is None
    assert result.price_id is not None

    new_price = session.get(Price, result.price_id)
    assert float(new_price.price) == 6.50
    assert new_price.created_by_user_id == user.id
    assert new_price.source_order_item_id == item.id
    assert new_price.valid_to is None


def test_confirm_price_updates_applies_create_when_no_active_price(
    db_session, make_supplier, make_material, make_price, make_project, make_user
):
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )
    session.query(Price).filter_by(material_id=material.id, supplier_id=supplier.id).delete()
    session.commit()
    set_order_item_fields(session, order.id, item.id, confirmed_price=8.00)
    user = _unique_user(make_user)

    results = confirm_price_updates(
        session,
        order_id=order.id,
        selections=[{"order_item_id": item.id, "apply": True}],
        current_user_id=user.id,
    )

    assert results[0].applied is True
    assert results[0].action == "create"
    new_price = session.get(Price, results[0].price_id)
    assert float(new_price.price) == 8.00


def test_confirm_price_updates_apply_false_row_is_not_applied(
    db_session, make_supplier, make_material, make_price, make_project, make_user
):
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )
    set_order_item_fields(session, order.id, item.id, confirmed_price=6.50)
    user = _unique_user(make_user)

    results = confirm_price_updates(
        session,
        order_id=order.id,
        selections=[{"order_item_id": item.id, "apply": False}],
        current_user_id=user.id,
    )

    assert results[0].applied is False
    assert results[0].action is None
    assert results[0].price_id is None
    assert results[0].error is None
    # Price table untouched.
    active = (
        session.query(Price)
        .filter_by(material_id=material.id, supplier_id=supplier.id, valid_to=None)
        .one()
    )
    assert float(active.price) == 5.00


def test_confirm_price_updates_revalidates_when_active_price_changed_since_detection(
    db_session, make_supplier, make_material, make_price, make_project, make_user
):
    """Staleness: if the active Price was updated by someone else between
    the divergence being shown on screen and the confirm click, and it now
    matches confirmed_price, this row must error out, not blindly re-apply
    — ADR-0030 п.4.3."""
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )
    set_order_item_fields(session, order.id, item.id, confirmed_price=6.50)
    # Someone else already updated the active Price to match confirmed_price.
    active = session.query(Price).filter_by(
        material_id=material.id, supplier_id=supplier.id, valid_to=None
    ).one()
    active.price = 6.50
    session.commit()
    user = _unique_user(make_user)

    results = confirm_price_updates(
        session,
        order_id=order.id,
        selections=[{"order_item_id": item.id, "apply": True}],
        current_user_id=user.id,
    )

    assert results[0].applied is False
    assert results[0].error is not None
    assert results[0].price_id is None


def test_confirm_price_updates_revalidates_when_confirmed_price_cleared_since_detection(
    db_session, make_supplier, make_material, make_price, make_project, make_user
):
    """If confirmed_price was cleared by another PATCH between detection and
    confirmation, the row must error, not apply a stale value."""
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )
    set_order_item_fields(session, order.id, item.id, confirmed_price=6.50)
    set_order_item_fields(session, order.id, item.id, confirmed_price=None)
    user = _unique_user(make_user)

    results = confirm_price_updates(
        session,
        order_id=order.id,
        selections=[{"order_item_id": item.id, "apply": True}],
        current_user_id=user.id,
    )

    assert results[0].applied is False
    assert results[0].error is not None


def test_confirm_price_updates_one_bad_row_does_not_block_others(
    db_session, make_supplier, make_material, make_price, make_project, make_user
):
    """Per-row independence — ADR-0030 п.4.3, precedent ADR-0018 §4."""
    session, *_ = db_session
    order_good, item_good, supplier_good, material_good = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )
    order_bad, item_bad, supplier_bad, material_bad = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )
    set_order_item_fields(session, order_good.id, item_good.id, confirmed_price=6.50)
    set_order_item_fields(session, order_bad.id, item_bad.id, confirmed_price=6.50)
    # Make the "bad" row stale by clearing confirmed_price after the fact.
    set_order_item_fields(session, order_bad.id, item_bad.id, confirmed_price=None)
    user = _unique_user(make_user)

    good_results = confirm_price_updates(
        session,
        order_id=order_good.id,
        selections=[{"order_item_id": item_good.id, "apply": True}],
        current_user_id=user.id,
    )
    bad_results = confirm_price_updates(
        session,
        order_id=order_bad.id,
        selections=[{"order_item_id": item_bad.id, "apply": True}],
        current_user_id=user.id,
    )

    assert good_results[0].applied is True
    assert bad_results[0].applied is False


def test_confirm_price_updates_mixed_batch_good_row_applies_despite_bad_row_in_same_call(
    db_session, make_supplier, make_material, make_price, make_project, make_user
):
    """The literal per-request case: two rows in the same confirm-price-
    updates call, one goes stale, the other must still apply."""
    session, *_ = db_session
    order = None
    # Build two OrderItems in the same Order/supplier pair so one request
    # can select both.
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material_a = make_material()
    material_b = make_material()
    make_price(material_a, supplier, price=5.00, availability=10)
    make_price(material_b, supplier, price=5.00, availability=10)
    project = make_project([(material_a, 10), (material_b, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    order = orders[0]
    item_a = next(i for i in order.items if i.material_id == material_a.id)
    item_b = next(i for i in order.items if i.material_id == material_b.id)

    set_order_item_fields(session, order.id, item_a.id, confirmed_price=6.50)
    set_order_item_fields(session, order.id, item_b.id, confirmed_price=7.00)
    # item_b goes stale.
    set_order_item_fields(session, order.id, item_b.id, confirmed_price=None)
    user = _unique_user(make_user)

    results = confirm_price_updates(
        session,
        order_id=order.id,
        selections=[
            {"order_item_id": item_a.id, "apply": True},
            {"order_item_id": item_b.id, "apply": True},
        ],
        current_user_id=user.id,
    )

    by_item = {r.order_item_id: r for r in results}
    assert by_item[item_a.id].applied is True
    assert by_item[item_b.id].applied is False
    assert by_item[item_b.id].error is not None


def test_confirm_price_updates_unknown_order_item_id_errors_without_raising(
    db_session, make_supplier, make_material, make_price, make_project, make_user
):
    session, *_ = db_session
    order, item, supplier, material = _make_order_item(
        session, make_supplier, make_material, make_price, make_project
    )
    user = _unique_user(make_user)
    import uuid

    unknown_id = uuid.uuid4()

    results = confirm_price_updates(
        session,
        order_id=order.id,
        selections=[{"order_item_id": unknown_id, "apply": True}],
        current_user_id=user.id,
    )

    assert results[0].applied is False
    assert results[0].error is not None
