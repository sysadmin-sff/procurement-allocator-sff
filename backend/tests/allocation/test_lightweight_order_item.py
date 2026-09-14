"""Tests for the lightweight OrderItem (material_id=None, raw_description
filled) introduced by ADR-0033: POST /orders/{order_id}/items/raw, the
find-replacement/replace-and-order/_detect_price_divergence guards on such a
row, the order_response_parser fallback, and that the three money-aggregating
functions (order_expected_totals, received_price_delta, expected_tax_amount)
already treat a light row like any other.
"""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.allocation.order_service import create_orders_for_run, order_expected_totals
from app.allocation.service import run_allocation
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
    email = f"employee-lightweight{_employee_email_counter[0]}@screen-factory-florida.com"
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


def _add_light_item(session, order, quantity=1, quoted_price=5.00, raw_description="Light row"):
    item = OrderItem(
        order_id=order.id,
        material_id=None,
        raw_description=raw_description,
        quantity=quantity,
        quoted_price=quoted_price,
    )
    session.add(item)
    session.commit()
    return item


# --- POST /orders/{order_id}/items/raw ---


def test_add_raw_item_on_draft_order_returns_201_with_null_material_id(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/raw",
        json={
            "raw_description": "Extra bracket supplier threw in",
            "quantity": 2,
            "quoted_price": 18.95,
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["material_id"] is None
    assert body["raw_description"] == "Extra bracket supplier threw in"
    assert body["quantity"] == 2
    assert body["quoted_price"] == 18.95
    assert body["order_id"] == str(order.id)


def test_add_raw_item_on_non_draft_order_returns_409(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    order.status = "sent"
    session.commit()
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/raw",
        json={"raw_description": "Extra item", "quantity": 1, "quoted_price": 5.00},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409


def test_add_raw_item_rejects_material_id_in_body(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """The endpoint must not silently ignore an unexpected material_id — the
    schema should reject it outright (extra field not accepted)."""
    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/raw",
        json={
            "raw_description": "Extra item",
            "quantity": 1,
            "quoted_price": 5.00,
            "material_id": str(uuid.uuid4()),
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    # The body's material_id must reflect the created row (None), proving the
    # extra "material_id" in the request payload was ignored by the schema,
    # not applied.
    assert body["material_id"] is None


# --- find_replacement_candidates / replace_and_sync_order guards ---


def test_find_replacement_candidates_422_on_light_row(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    light_item = _add_light_item(session, order)
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/{light_item.id}/find-replacement",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_replace_and_sync_order_422_on_light_row(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    light_item = _add_light_item(session, order)
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/{light_item.id}/replace-and-order",
        json={"supplier_id": str(uuid.uuid4())},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


# --- PATCH confirmed_price on a light row — 200, no price_divergence ---


def test_patch_confirmed_price_on_light_row_succeeds_without_divergence(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    light_item = _add_light_item(session, order)
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/orders/{order.id}/items/{light_item.id}",
        json={"confirmed_price": 6.50},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["confirmed_price"] == 6.50
    assert body["price_divergence"] is None


# --- order_response_parser fallback on a light row ---


def test_reparsing_order_with_light_row_does_not_crash(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """Regression: _order_items_context used to always read
    item.material.canonical_name unconditionally — a light row (material_id
    None) would AttributeError on None.canonical_name."""
    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    light_item = _add_light_item(
        session, order, raw_description="Supplier-only extra line"
    )
    client = _employee_client(make_user, make_session)

    with patch(
        "app.order_response_parser.service.parse_order_response_document",
        return_value=[],
    ):
        response = client.post(
            f"/orders/{order.id}/parse-response",
            files={"file": ("response.pdf", b"%PDF-1.4 fake", "application/pdf")},
            headers={"X-CSRF-Token": CSRF},
        )

    assert response.status_code == 200
    body = response.json()
    missing_ids = {m["order_item_id"] for m in body["missing"]}
    assert str(light_item.id) in missing_ids
    light_missing = next(m for m in body["missing"] if m["order_item_id"] == str(light_item.id))
    assert light_missing["canonical_name"] == "Supplier-only extra line"
    assert light_missing["material_id"] is None


# --- money paths include the light row correctly ---


def test_order_expected_totals_includes_light_row(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    # order already has one normal item: quantity=10, quoted_price=5.00 -> 50.00
    _add_light_item(session, order, quantity=3, quoted_price=10.00)
    session.refresh(order)

    totals = order_expected_totals(order)

    assert totals["expected_goods_total"] == 50.00 + 30.00


def test_expected_tax_amount_includes_light_row(
    db_session, make_supplier, make_material, make_price, make_project
):
    from app.allocation.tax import calculate_tax_dollars

    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    _add_light_item(session, order, quantity=3, quoted_price=10.00)
    session.refresh(order)

    totals = order_expected_totals(order)

    assert totals["expected_tax_amount"] == calculate_tax_dollars(50.00 + 30.00)


def test_received_price_delta_computed_for_light_row(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _supplier, _material, _project, _run, order = _draft_order_with_item(
        session, make_supplier, make_material, make_price, make_project
    )
    light_item = _add_light_item(session, order, quoted_price=10.00)
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/orders/{order.id}/items/{light_item.id}",
        json={"received_price": 11.00},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["received_price_delta"] == 1.00
    assert body["received_price_delta_pct"] == 10.0
