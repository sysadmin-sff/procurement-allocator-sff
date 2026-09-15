"""Tests for GET /orders/{order_id}/items/{item_id}/price-history —
employee-accessible active+historical Price rows for (item.material_id,
order.supplier_id), mirroring MaterialPricesPanel's "активна"/"историческая"
vocabulary on OrderDetailPage without requiring admin (price.py's GET
/prices is require_role("admin") for the whole router, ADR-0024 §4).
"""

import uuid

from fastapi.testclient import TestClient

from app.allocation.order_service import create_orders_for_run
from app.allocation.service import run_allocation
from app.api.price import version_price
from app.main import app
from app.models import OrderItem

CSRF = "test-csrf-token"
_employee_email_counter = [0]


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def _employee_client(make_user, make_session):
    _employee_email_counter[0] += 1
    email = f"employee-price-history{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session)


def _draft_order_with_item(session, make_supplier, make_material, make_price, make_project):
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    order = orders[0]
    return supplier, material, project, run, order


def test_returns_active_and_historical_rows_for_the_orders_supplier(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier, material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    item = order.items[0]
    # A newer version closes the price the order was snapshotted from —
    # version_price closes the existing active row and opens a new one.
    version_price(session, material_id=material.id, supplier_id=supplier.id, price=6.00)
    client = _employee_client(make_user, make_session)

    response = client.get(f"/orders/{order.id}/items/{item.id}/price-history")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    active = [p for p in body if p["valid_to"] is None]
    historical = [p for p in body if p["valid_to"] is not None]
    assert len(active) == 1
    assert len(historical) == 1
    assert active[0]["price"] == 6.00
    assert historical[0]["price"] == 5.00


def test_employee_role_gets_200_not_403(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """The whole point of this endpoint: price.py's GET /prices is
    admin-only (ADR-0024 §4) — an employee must be able to see price
    history for their own Order without that role."""
    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    item = order.items[0]
    client = _employee_client(make_user, make_session)

    response = client.get(f"/orders/{order.id}/items/{item.id}/price-history")

    assert response.status_code == 200


def test_scoped_to_the_orders_supplier_not_every_supplier(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """Unlike GET /materials/{id}/prices (all suppliers), this endpoint
    answers "what has this Order's specific supplier's price looked like",
    not "who else sells this material" — a different, unrelated supplier's
    price on the same material must not appear."""
    session, *_ = db_session
    _supplier, material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    item = order.items[0]
    other_supplier = make_supplier(name="Unrelated Supplier")
    make_price(material, other_supplier, price=99.00, availability=10)
    client = _employee_client(make_user, make_session)

    response = client.get(f"/orders/{order.id}/items/{item.id}/price-history")

    assert response.status_code == 200
    body = response.json()
    assert all(p["supplier_id"] != str(other_supplier.id) for p in body)


def test_order_not_found_returns_404(db_session, make_user, make_session):
    client = _employee_client(make_user, make_session)

    response = client.get(f"/orders/{uuid.uuid4()}/items/{uuid.uuid4()}/price-history")

    assert response.status_code == 404


def test_item_not_found_in_order_returns_404(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    client = _employee_client(make_user, make_session)

    response = client.get(f"/orders/{order.id}/items/{uuid.uuid4()}/price-history")

    assert response.status_code == 404


def test_lightweight_item_returns_422(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    light_item = OrderItem(
        order_id=order.id,
        material_id=None,
        raw_description="Light row",
        quantity=1,
        quoted_price=5.00,
    )
    session.add(light_item)
    session.commit()
    client = _employee_client(make_user, make_session)

    response = client.get(f"/orders/{order.id}/items/{light_item.id}/price-history")

    assert response.status_code == 422


def test_sorted_by_valid_from_descending(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier, material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    item = order.items[0]
    version_price(session, material_id=material.id, supplier_id=supplier.id, price=6.00)
    version_price(session, material_id=material.id, supplier_id=supplier.id, price=7.00)
    client = _employee_client(make_user, make_session)

    response = client.get(f"/orders/{order.id}/items/{item.id}/price-history")

    body = response.json()
    valid_froms = [p["valid_from"] for p in body]
    assert valid_froms == sorted(valid_froms, reverse=True)
