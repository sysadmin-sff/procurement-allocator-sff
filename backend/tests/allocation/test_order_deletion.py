"""Tests for standalone single-Order deletion — ADR-0037.

Covers: DELETE /orders/{order_id} on a draft Order (success, cascade to
OrderItem, Price.source_order_item_id nulled), on a non-draft Order (409,
nothing deleted), on an unknown id (404), and that the endpoint is reachable
by an employee (not admin-only — regression on ADR-0024 §4).
"""

import uuid

from fastapi.testclient import TestClient

from app.allocation.order_service import (
    OrderNotDraftError,
    OrderNotFoundError,
    delete_order,
    delete_order_by_id,
)
from app.allocation.service import run_allocation
from app.main import app
from app.models import Order, OrderItem, Price

CSRF = "test-csrf-token"
_employee_email_counter = [0]


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def _employee_client(make_user, make_session):
    _employee_email_counter[0] += 1
    email = f"employee-order-deletion{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session)


def _setup_single_supplier_project(make_supplier, make_material, make_price, make_project):
    supplier = make_supplier(name="Solo Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    return supplier, material, project


def test_delete_order_endpoint_removes_draft_order(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    orders = create_orders_for_run_helper(session, project.id, run.id)
    order_id = orders[0].id
    item_id = orders[0].items[0].id
    client = _employee_client(make_user, make_session)

    response = client.delete(f"/orders/{order_id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 204
    session.expire_all()
    assert session.get(Order, order_id) is None
    assert session.get(OrderItem, item_id) is None


def test_delete_order_endpoint_nulls_price_source_order_item_id(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    from app.allocation.order_service import confirm_price_updates, set_order_item_fields

    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    orders = create_orders_for_run_helper(session, project.id, run.id)
    order_id = orders[0].id
    item_id = orders[0].items[0].id
    user = make_user(email="order-deletion-price-source@screen-factory-florida.com")

    set_order_item_fields(session, order_id, item_id, confirmed_price=6.00)
    results = confirm_price_updates(
        session,
        order_id=order_id,
        selections=[{"order_item_id": item_id, "apply": True}],
        current_user_id=user.id,
    )
    price_id = results[0].price_id
    assert session.get(Price, price_id).source_order_item_id == item_id
    client = _employee_client(make_user, make_session)

    response = client.delete(f"/orders/{order_id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 204
    session.expire_all()
    survived_price = session.get(Price, price_id)
    assert survived_price is not None
    assert survived_price.source_order_item_id is None


def test_delete_order_endpoint_returns_409_for_non_draft_and_deletes_nothing(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    orders = create_orders_for_run_helper(session, project.id, run.id)
    order_id = orders[0].id
    orders[0].status = "sent"
    session.commit()
    client = _employee_client(make_user, make_session)

    response = client.delete(f"/orders/{order_id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 409
    assert response.json()["detail"] == "Ордер уже не в статусе черновика — удаление недоступно."
    session.expire_all()
    assert session.get(Order, order_id) is not None


def test_delete_order_endpoint_returns_404_for_unknown_id(make_user, make_session):
    client = _employee_client(make_user, make_session)

    response = client.delete(f"/orders/{uuid.uuid4()}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 404


def test_delete_order_endpoint_reachable_by_employee_role(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """Regression on ADR-0024 §4: order.py is get_current_user (any role),
    not admin-only — deleting one's own draft order is operational work."""
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    orders = create_orders_for_run_helper(session, project.id, run.id)
    order_id = orders[0].id
    employee = make_user(
        email="order-deletion-employee-role@screen-factory-florida.com", role="employee"
    )
    employee_session = make_session(employee, csrf_token=CSRF)
    client = _client_as(employee_session)

    response = client.delete(f"/orders/{order_id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 204


def test_delete_order_service_function_removes_order(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    orders = create_orders_for_run_helper(session, project.id, run.id)
    order = orders[0]
    order_id = order.id

    delete_order(session, order)
    session.commit()

    assert session.get(Order, order_id) is None


def test_delete_order_by_id_raises_not_found():
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        try:
            delete_order_by_id(session, uuid.uuid4())
            raise AssertionError("expected OrderNotFoundError")
        except OrderNotFoundError:
            pass
    finally:
        session.close()


def test_delete_order_by_id_raises_not_draft(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    orders = create_orders_for_run_helper(session, project.id, run.id)
    order = orders[0]
    order.status = "sent"
    session.commit()

    try:
        delete_order_by_id(session, order.id)
        raise AssertionError("expected OrderNotDraftError")
    except OrderNotDraftError:
        pass

    session.expire_all()
    assert session.get(Order, order.id) is not None


def create_orders_for_run_helper(session, project_id, run_id):
    from app.allocation.order_service import create_orders_for_run

    return create_orders_for_run(session, project_id, run_id)
