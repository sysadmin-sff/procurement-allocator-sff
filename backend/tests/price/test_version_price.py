"""Tests for version_price — the shared versioning primitive extracted from
update_price (ADR-0030 п.5). Called directly here (service layer, not via
the admin-only /prices HTTP route) since ADR-0030's whole point is that
order.py calls this function without going through price.py at all.
"""

import datetime

from app.api.price import version_price
from app.models import Price


def test_version_price_creates_when_no_active_price_exists(
    db_session, make_material, make_supplier
):
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()

    price = version_price(
        session, material_id=material.id, supplier_id=supplier.id, price=12.50
    )

    assert price.id is not None
    assert float(price.price) == 12.50
    assert price.valid_to is None
    assert price.valid_from == datetime.date.today()


def test_version_price_update_closes_old_and_creates_new(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()
    old = make_price(material, supplier, price=10.0, availability=5, min_order_qty=2)

    new = version_price(
        session, material_id=material.id, supplier_id=supplier.id, price=20.0
    )

    session.refresh(old)
    assert old.valid_to == datetime.date.today()
    assert new.id != old.id
    assert float(new.price) == 20.0
    assert new.valid_to is None


def test_version_price_update_inherits_unset_fields_from_closed_row(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()
    make_price(material, supplier, price=10.0, availability=42, min_order_qty=7)

    new = version_price(
        session, material_id=material.id, supplier_id=supplier.id, price=20.0
    )

    assert new.currency == "USD"
    assert new.availability == 42
    assert new.min_order_qty == 7


def test_version_price_create_does_not_touch_unrelated_pair(
    db_session, make_material, make_supplier, make_price
):
    """Creating a new active price for (material, supplier) must not close
    an active price belonging to a different material/supplier pair."""
    session, *_ = db_session
    material_a = make_material()
    material_b = make_material()
    supplier = make_supplier()
    unrelated = make_price(material_a, supplier, price=5.0)

    version_price(session, material_id=material_b.id, supplier_id=supplier.id, price=8.0)

    session.refresh(unrelated)
    assert unrelated.valid_to is None


def test_version_price_sets_created_by_and_source_order_item_when_passed(
    db_session, make_material, make_supplier, make_user
):
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()
    user = make_user()
    fake_item_id = None  # order-item tests cover a real FK; None is valid here

    price = version_price(
        session,
        material_id=material.id,
        supplier_id=supplier.id,
        price=15.0,
        created_by_user_id=user.id,
        source_order_item_id=fake_item_id,
    )

    assert price.created_by_user_id == user.id
    assert price.source_order_item_id is None


def test_version_price_defaults_created_by_and_source_order_item_to_none(
    db_session, make_material, make_supplier
):
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()

    price = version_price(
        session, material_id=material.id, supplier_id=supplier.id, price=15.0
    )

    assert price.created_by_user_id is None
    assert price.source_order_item_id is None


def test_version_price_explicit_fields_override_inherited_ones(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()
    make_price(material, supplier, price=10.0, availability=42, min_order_qty=7)

    new = version_price(
        session,
        material_id=material.id,
        supplier_id=supplier.id,
        price=20.0,
        availability=99,
        min_order_qty=1,
        currency="EUR",
    )

    assert new.availability == 99
    assert new.min_order_qty == 1
    assert new.currency == "EUR"


def test_version_price_accepts_explicit_valid_from_and_valid_to(
    db_session, make_material, make_supplier
):
    """update_price (PUT /prices/{id}) supports admin-supplied dates
    (backdating, pre-closing a row) — version_price must accept them as
    overrides on top of the today/None defaults, not just use today always."""
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()
    backdated_from = datetime.date.today() - datetime.timedelta(days=30)
    backdated_to = datetime.date.today() - datetime.timedelta(days=1)

    price = version_price(
        session,
        material_id=material.id,
        supplier_id=supplier.id,
        price=5.0,
        valid_from=backdated_from,
        valid_to=backdated_to,
    )

    assert price.valid_from == backdated_from
    assert price.valid_to == backdated_to


def test_version_price_create_case_does_not_attempt_to_close_nonexistent_row(
    db_session, make_material, make_supplier
):
    """Case (в) from ADR-0030 п.2: no active row for the pair at all. Must
    not raise from trying to close something that doesn't exist, and must
    proceed straight to creation."""
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()

    price = version_price(
        session, material_id=material.id, supplier_id=supplier.id, price=7.25
    )

    assert price.valid_to is None
    count = (
        session.query(Price)
        .filter_by(material_id=material.id, supplier_id=supplier.id)
        .count()
    )
    assert count == 1
