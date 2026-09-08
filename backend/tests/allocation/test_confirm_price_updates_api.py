"""API-level tests for POST /orders/{order_id}/confirm-price-updates and
the price_divergence field on PATCH .../items/{item_id} — ADR-0030 п.4.
Covers the narrow permission exception (ADR-0030 §6/Альтернативы): this
endpoint lives in order.py (get_current_user, any role) while price.py
stays admin-only — an employee must be able to call it, unlike /prices/**.
"""

import uuid

from fastapi.testclient import TestClient

from app.allocation.order_service import create_orders_for_run
from app.allocation.service import run_allocation
from app.main import app
from app.models import Price

CSRF = "test-csrf-token"
_employee_email_counter = [0]
_admin_email_counter = [0]


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def _employee_client(make_user, make_session):
    _employee_email_counter[0] += 1
    email = f"employee-confirm-price{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session)


def _admin_client(make_user, make_session):
    _admin_email_counter[0] += 1
    email = f"admin-confirm-price{_admin_email_counter[0]}@screen-factory-florida.com"
    admin = make_user(email=email, role="admin")
    admin_session = make_session(admin, csrf_token=CSRF)
    return _client_as(admin_session)


def _make_order(session, make_supplier, make_material, make_price, make_project, price=5.00):
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=price, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    return orders[0], orders[0].items[0], supplier, material


def test_patch_order_item_response_includes_price_divergence_on_mismatch(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    order, item, supplier, material = _make_order(
        session, make_supplier, make_material, make_price, make_project
    )
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/orders/{order.id}/items/{item.id}",
        json={"confirmed_price": 6.50},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    divergence = body["price_divergence"]
    assert divergence is not None
    assert divergence["action"] == "update"
    assert divergence["current_price"] == 5.00
    assert divergence["confirmed_price"] == 6.50
    assert divergence["material_id"] == str(material.id)
    assert divergence["supplier_id"] == str(supplier.id)


def test_patch_order_item_response_price_divergence_null_when_matching(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    order, item, supplier, material = _make_order(
        session, make_supplier, make_material, make_price, make_project
    )
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/orders/{order.id}/items/{item.id}",
        json={"confirmed_price": 5.00},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.json()["price_divergence"] is None


def test_patch_order_item_response_price_divergence_null_when_confirmed_price_not_touched(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    order, item, supplier, material = _make_order(
        session, make_supplier, make_material, make_price, make_project
    )
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/orders/{order.id}/items/{item.id}",
        json={"received_price": 4.90},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.json()["price_divergence"] is None


def test_confirm_price_updates_applies_selected_row(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    order, item, supplier, material = _make_order(
        session, make_supplier, make_material, make_price, make_project
    )
    client = _employee_client(make_user, make_session)
    client.patch(
        f"/orders/{order.id}/items/{item.id}",
        json={"confirmed_price": 6.50},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.post(
        f"/orders/{order.id}/confirm-price-updates",
        json={"selections": [{"order_item_id": str(item.id), "apply": True}]},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["order_item_id"] == str(item.id)
    assert results[0]["applied"] is True
    assert results[0]["action"] == "update"
    assert results[0]["price_id"] is not None
    assert results[0]["error"] is None

    active = session.query(Price).filter_by(
        material_id=material.id, supplier_id=supplier.id, valid_to=None
    ).one()
    assert float(active.price) == 6.50


def test_confirm_price_updates_apply_false_leaves_price_untouched(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    order, item, supplier, material = _make_order(
        session, make_supplier, make_material, make_price, make_project
    )
    client = _employee_client(make_user, make_session)
    client.patch(
        f"/orders/{order.id}/items/{item.id}",
        json={"confirmed_price": 6.50},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.post(
        f"/orders/{order.id}/confirm-price-updates",
        json={"selections": [{"order_item_id": str(item.id), "apply": False}]},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["applied"] is False
    active = session.query(Price).filter_by(
        material_id=material.id, supplier_id=supplier.id, valid_to=None
    ).one()
    assert float(active.price) == 5.00


def test_confirm_price_updates_stale_row_returns_error_without_500(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    order, item, supplier, material = _make_order(
        session, make_supplier, make_material, make_price, make_project
    )
    client = _employee_client(make_user, make_session)
    client.patch(
        f"/orders/{order.id}/items/{item.id}",
        json={"confirmed_price": 6.50},
        headers={"X-CSRF-Token": CSRF},
    )
    client.patch(
        f"/orders/{order.id}/items/{item.id}",
        json={"confirmed_price": None},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.post(
        f"/orders/{order.id}/confirm-price-updates",
        json={"selections": [{"order_item_id": str(item.id), "apply": True}]},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["applied"] is False
    assert results[0]["error"] is not None


def test_confirm_price_updates_partial_success_within_one_request(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """Two rows in one request, one goes stale after detection — the other
    still applies. See ADR-0030 п.4.3 per-row independence."""
    session, *_ = db_session
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
    client = _employee_client(make_user, make_session)

    client.patch(
        f"/orders/{order.id}/items/{item_a.id}",
        json={"confirmed_price": 6.50},
        headers={"X-CSRF-Token": CSRF},
    )
    client.patch(
        f"/orders/{order.id}/items/{item_b.id}",
        json={"confirmed_price": 7.00},
        headers={"X-CSRF-Token": CSRF},
    )
    # item_b goes stale before confirmation.
    client.patch(
        f"/orders/{order.id}/items/{item_b.id}",
        json={"confirmed_price": None},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.post(
        f"/orders/{order.id}/confirm-price-updates",
        json={
            "selections": [
                {"order_item_id": str(item_a.id), "apply": True},
                {"order_item_id": str(item_b.id), "apply": True},
            ]
        },
        headers={"X-CSRF-Token": CSRF},
    )

    results = {r["order_item_id"]: r for r in response.json()["results"]}
    assert results[str(item_a.id)]["applied"] is True
    assert results[str(item_b.id)]["applied"] is False


def test_confirm_price_updates_unknown_order_item_returns_error_row_not_500(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    order, item, supplier, material = _make_order(
        session, make_supplier, make_material, make_price, make_project
    )
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/confirm-price-updates",
        json={"selections": [{"order_item_id": str(uuid.uuid4()), "apply": True}]},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["applied"] is False
    assert response.json()["results"][0]["error"] is not None


def test_confirm_price_updates_returns_404_for_unknown_order(make_user, make_session):
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{uuid.uuid4()}/confirm-price-updates",
        json={"selections": []},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_confirm_price_updates_sets_created_by_to_current_user(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    order, item, supplier, material = _make_order(
        session, make_supplier, make_material, make_price, make_project
    )
    _employee_email_counter[0] += 1
    email = f"employee-confirm-price{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    client = _client_as(employee_session)
    client.patch(
        f"/orders/{order.id}/items/{item.id}",
        json={"confirmed_price": 6.50},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.post(
        f"/orders/{order.id}/confirm-price-updates",
        json={"selections": [{"order_item_id": str(item.id), "apply": True}]},
        headers={"X-CSRF-Token": CSRF},
    )

    price_id = response.json()["results"][0]["price_id"]
    price = session.get(Price, price_id)
    assert price.created_by_user_id == employee.id
    assert price.source_order_item_id == item.id


def test_confirm_price_updates_as_employee_succeeds(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """Narrow exception, ADR-0030 §6/Альтернативы: employee (not admin) can
    call this endpoint — regression proving the exception is real, unlike
    price.py which stays 403 for employee (see test below)."""
    session, *_ = db_session
    order, item, supplier, material = _make_order(
        session, make_supplier, make_material, make_price, make_project
    )
    client = _employee_client(make_user, make_session)
    client.patch(
        f"/orders/{order.id}/items/{item.id}",
        json={"confirmed_price": 6.50},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.post(
        f"/orders/{order.id}/confirm-price-updates",
        json={"selections": [{"order_item_id": str(item.id), "apply": True}]},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200


def test_prices_router_still_403s_employee_after_this_change(make_user, make_session):
    """Regression guard on ADR-0024 §4: price.py stays admin-only in its
    entirety — this ADR does not loosen it anywhere."""
    _employee_email_counter[0] += 1
    email = f"employee-confirm-price-guard{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    client = _client_as(employee_session)

    response = client.get("/prices")

    assert response.status_code == 403


def test_confirm_price_updates_no_session_returns_401():
    client = TestClient(app)
    response = client.post(
        f"/orders/{uuid.uuid4()}/confirm-price-updates",
        json={"selections": []},
    )
    assert response.status_code == 401
