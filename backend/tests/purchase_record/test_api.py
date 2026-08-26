"""Tests for PurchaseRecord CRUD and plan/fact total aggregation — ADR-0008.

Covers: free-text/optional-material CRUD, per-project and per-supplier
aggregation against Order.total_amount, None (not 0) delta when a
project/supplier has no Order yet, an unplanned "с колёс" supplier with no
Order at all, and 404s.
"""

import uuid

from fastapi.testclient import TestClient

from app.allocation.order_service import create_orders_for_run
from app.allocation.service import run_allocation
from app.main import app
from app.purchase_records.service import (
    PurchaseRecordNotFoundError,
    create_purchase_record,
    delete_purchase_record,
    update_purchase_record,
)

CSRF = "test-csrf-token"
_employee_email_counter = [0]


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def _employee_client(make_user, make_session):
    _employee_email_counter[0] += 1
    email = f"employee-purchase-record{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session)


def test_create_purchase_record_via_api(
    db_session, make_supplier, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    project = make_project([])
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/purchase-records",
        json={
            "supplier_id": str(supplier.id),
            "raw_description": '84" PREMIER SCREEN 18/14"',
            "quantity": 3,
            "unit_price": 42.50,
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["raw_description"] == '84" PREMIER SCREEN 18/14"'
    assert body["quantity"] == 3
    assert body["unit_price"] == 42.50
    assert body["material_id"] is None
    assert body["project_id"] == str(project.id)


def test_create_purchase_record_with_material_id(
    db_session, make_supplier, make_material, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material()
    project = make_project([])
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/purchase-records",
        json={
            "supplier_id": str(supplier.id),
            "raw_description": "Some raw name",
            "quantity": 1,
            "unit_price": 10.0,
            "material_id": str(material.id),
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    assert response.json()["material_id"] == str(material.id)


def test_create_purchase_record_rejects_zero_quantity(
    db_session, make_supplier, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    project = make_project([])
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/purchase-records",
        json={
            "supplier_id": str(supplier.id),
            "raw_description": "X",
            "quantity": 0,
            "unit_price": 10.0,
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_create_purchase_record_rejects_negative_price(
    db_session, make_supplier, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    project = make_project([])
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/purchase-records",
        json={
            "supplier_id": str(supplier.id),
            "raw_description": "X",
            "quantity": 1,
            "unit_price": -5.0,
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_create_purchase_record_allows_zero_price(
    db_session, make_supplier, make_project, make_user, make_session
):
    """unit_price >= 0, not > 0 — a free/promotional line is representable."""
    session, *_ = db_session
    supplier = make_supplier()
    project = make_project([])
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/purchase-records",
        json={
            "supplier_id": str(supplier.id),
            "raw_description": "Free sample",
            "quantity": 1,
            "unit_price": 0.0,
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201


def test_create_purchase_record_returns_404_for_unknown_project(
    db_session, make_supplier, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{uuid.uuid4()}/purchase-records",
        json={
            "supplier_id": str(supplier.id),
            "raw_description": "X",
            "quantity": 1,
            "unit_price": 1.0,
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_create_purchase_record_for_supplier_with_no_order_in_project(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """Ordered "с колёс" from a supplier that never had an AllocationRun/Order
    in this project at all — must not fail. See ADR-0008 п.2."""
    session, *_ = db_session
    planned_supplier = make_supplier(name="Planned", flat_fee=0.0, free_shipping_threshold=0.0)
    unplanned_supplier = make_supplier(name="Unplanned")
    material = make_material()
    make_price(material, planned_supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)
    create_orders_for_run(session, project.id, run.id)
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/purchase-records",
        json={
            "supplier_id": str(unplanned_supplier.id),
            "raw_description": "Emergency buy",
            "quantity": 2,
            "unit_price": 15.0,
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201


def test_update_purchase_record(db_session, make_supplier, make_project, make_user, make_session):
    session, *_ = db_session
    supplier = make_supplier()
    other_supplier = make_supplier(name="Other")
    project = make_project([])
    record = create_purchase_record(
        session,
        project_id=project.id,
        supplier_id=supplier.id,
        raw_description="Original",
        quantity=1,
        unit_price=10.0,
        material_id=None,
    )
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/projects/{project.id}/purchase-records/{record.id}",
        json={
            "supplier_id": str(other_supplier.id),
            "raw_description": "Corrected",
            "quantity": 5,
            "unit_price": 20.0,
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["raw_description"] == "Corrected"
    assert body["quantity"] == 5
    assert body["unit_price"] == 20.0
    assert body["supplier_id"] == str(other_supplier.id)


def test_update_purchase_record_returns_404_for_unknown_record(
    db_session, make_supplier, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    project = make_project([])
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/projects/{project.id}/purchase-records/{uuid.uuid4()}",
        json={
            "supplier_id": str(supplier.id),
            "raw_description": "X",
            "quantity": 1,
            "unit_price": 1.0,
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_update_purchase_record_returns_404_when_record_belongs_to_different_project(
    db_session, make_supplier, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    project_a = make_project([])
    project_b = make_project([])
    record = create_purchase_record(
        session,
        project_id=project_a.id,
        supplier_id=supplier.id,
        raw_description="X",
        quantity=1,
        unit_price=1.0,
        material_id=None,
    )
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/projects/{project_b.id}/purchase-records/{record.id}",
        json={
            "supplier_id": str(supplier.id),
            "raw_description": "X",
            "quantity": 1,
            "unit_price": 1.0,
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_delete_purchase_record(db_session, make_supplier, make_project, make_user, make_session):
    session, *_ = db_session
    supplier = make_supplier()
    project = make_project([])
    record = create_purchase_record(
        session,
        project_id=project.id,
        supplier_id=supplier.id,
        raw_description="X",
        quantity=1,
        unit_price=1.0,
        material_id=None,
    )
    client = _employee_client(make_user, make_session)

    response = client.delete(
        f"/projects/{project.id}/purchase-records/{record.id}",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 204
    listed = client.get(f"/projects/{project.id}/purchase-records")
    assert listed.json()["records"] == []


def test_delete_purchase_record_returns_404_for_unknown_record(
    db_session, make_supplier, make_project, make_user, make_session
):
    session, *_ = db_session
    project = make_project([])
    client = _employee_client(make_user, make_session)

    response = client.delete(
        f"/projects/{project.id}/purchase-records/{uuid.uuid4()}",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_update_purchase_record_service_raises_for_mismatched_project(
    db_session, make_supplier, make_project
):
    session, *_ = db_session
    supplier = make_supplier()
    project_a = make_project([])
    project_b = make_project([])
    record = create_purchase_record(
        session,
        project_id=project_a.id,
        supplier_id=supplier.id,
        raw_description="X",
        quantity=1,
        unit_price=1.0,
        material_id=None,
    )

    try:
        update_purchase_record(
            session,
            project_id=project_b.id,
            record_id=record.id,
            supplier_id=supplier.id,
            raw_description="Y",
            quantity=1,
            unit_price=1.0,
            material_id=None,
        )
        raise AssertionError("expected PurchaseRecordNotFoundError")
    except PurchaseRecordNotFoundError:
        pass


def test_delete_purchase_record_service_raises_for_mismatched_project(
    db_session, make_supplier, make_project
):
    session, *_ = db_session
    supplier = make_supplier()
    project_a = make_project([])
    project_b = make_project([])
    record = create_purchase_record(
        session,
        project_id=project_a.id,
        supplier_id=supplier.id,
        raw_description="X",
        quantity=1,
        unit_price=1.0,
        material_id=None,
    )

    try:
        delete_purchase_record(session, project_id=project_b.id, record_id=record.id)
        raise AssertionError("expected PurchaseRecordNotFoundError")
    except PurchaseRecordNotFoundError:
        pass


def test_list_returns_404_for_unknown_project(make_user, make_session):
    client = _employee_client(make_user, make_session)
    response = client.get(f"/projects/{uuid.uuid4()}/purchase-records")

    assert response.status_code == 404


def test_aggregates_null_when_no_order_exists_for_project(
    db_session, make_supplier, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    project = make_project([])
    create_purchase_record(
        session,
        project_id=project.id,
        supplier_id=supplier.id,
        raw_description="X",
        quantity=2,
        unit_price=10.0,
        material_id=None,
    )
    client = _employee_client(make_user, make_session)

    response = client.get(f"/projects/{project.id}/purchase-records")

    body = response.json()
    assert body["project_total"]["purchased_total"] == 20.0
    assert body["project_total"]["planned_total"] is None
    assert body["project_total"]["delta"] is None
    assert body["project_total"]["delta_pct"] is None

    supplier_total = next(
        s for s in body["supplier_totals"] if s["supplier_id"] == str(supplier.id)
    )
    assert supplier_total["purchased_total"] == 20.0
    assert supplier_total["planned_total"] is None
    assert supplier_total["delta"] is None


def test_aggregates_compare_against_order_total_amount_when_order_exists(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(name="Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=10.00, availability=100)
    project = make_project([(material, 10)])  # planned Order.total_amount = 100.00

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    assert float(orders[0].total_amount) == 100.00

    create_purchase_record(
        session,
        project_id=project.id,
        supplier_id=supplier.id,
        raw_description="Actual buy",
        quantity=10,
        unit_price=11.00,  # 110.00 actual vs 100.00 planned
        material_id=None,
    )
    client = _employee_client(make_user, make_session)

    response = client.get(f"/projects/{project.id}/purchase-records")
    body = response.json()

    assert body["project_total"]["purchased_total"] == 110.00
    assert body["project_total"]["planned_total"] == 100.00
    assert body["project_total"]["delta"] == 10.00
    assert round(body["project_total"]["delta_pct"], 4) == 10.0

    supplier_total = next(
        s for s in body["supplier_totals"] if s["supplier_id"] == str(supplier.id)
    )
    assert supplier_total["purchased_total"] == 110.00
    assert supplier_total["planned_total"] == 100.00
    assert supplier_total["delta"] == 10.00


def test_aggregates_sum_multiple_records_for_same_supplier(
    db_session, make_supplier, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    project = make_project([])
    create_purchase_record(
        session,
        project_id=project.id,
        supplier_id=supplier.id,
        raw_description="Line 1",
        quantity=2,
        unit_price=5.0,
        material_id=None,
    )
    create_purchase_record(
        session,
        project_id=project.id,
        supplier_id=supplier.id,
        raw_description="Line 2",
        quantity=3,
        unit_price=4.0,
        material_id=None,
    )
    client = _employee_client(make_user, make_session)

    response = client.get(f"/projects/{project.id}/purchase-records")
    body = response.json()

    assert len(body["records"]) == 2
    assert body["project_total"]["purchased_total"] == 22.0  # 2*5 + 3*4
    supplier_total = next(
        s for s in body["supplier_totals"] if s["supplier_id"] == str(supplier.id)
    )
    assert supplier_total["purchased_total"] == 22.0


def test_aggregates_keep_multiple_suppliers_separate(
    db_session, make_supplier, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier_a = make_supplier(name="A")
    supplier_b = make_supplier(name="B")
    project = make_project([])
    create_purchase_record(
        session,
        project_id=project.id,
        supplier_id=supplier_a.id,
        raw_description="A line",
        quantity=1,
        unit_price=100.0,
        material_id=None,
    )
    create_purchase_record(
        session,
        project_id=project.id,
        supplier_id=supplier_b.id,
        raw_description="B line",
        quantity=1,
        unit_price=50.0,
        material_id=None,
    )
    client = _employee_client(make_user, make_session)

    response = client.get(f"/projects/{project.id}/purchase-records")
    body = response.json()

    assert body["project_total"]["purchased_total"] == 150.0
    totals_by_supplier = {s["supplier_id"]: s["purchased_total"] for s in body["supplier_totals"]}
    assert totals_by_supplier[str(supplier_a.id)] == 100.0
    assert totals_by_supplier[str(supplier_b.id)] == 50.0


def test_aggregates_include_unplanned_supplier_with_null_planned_total(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """A supplier bought from "с колёс" (no Order in this project) still
    appears in supplier_totals, with planned_total=None. See ADR-0008 п.2."""
    session, *_ = db_session
    planned_supplier = make_supplier(name="Planned", flat_fee=0.0, free_shipping_threshold=0.0)
    unplanned_supplier = make_supplier(name="Unplanned")
    material = make_material()
    make_price(material, planned_supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)
    create_orders_for_run(session, project.id, run.id)

    create_purchase_record(
        session,
        project_id=project.id,
        supplier_id=unplanned_supplier.id,
        raw_description="Emergency buy",
        quantity=2,
        unit_price=15.0,
        material_id=None,
    )
    client = _employee_client(make_user, make_session)

    response = client.get(f"/projects/{project.id}/purchase-records")
    body = response.json()

    unplanned_total = next(
        s for s in body["supplier_totals"] if s["supplier_id"] == str(unplanned_supplier.id)
    )
    assert unplanned_total["purchased_total"] == 30.0
    assert unplanned_total["planned_total"] is None
    assert unplanned_total["delta"] is None

    planned_total = next(
        s for s in body["supplier_totals"] if s["supplier_id"] == str(planned_supplier.id)
    )
    assert planned_total["purchased_total"] == 0.0
    assert planned_total["planned_total"] == 50.0


def test_list_purchase_records_no_session_returns_401():
    client = TestClient(app)
    response = client.get(f"/projects/{uuid.uuid4()}/purchase-records")
    assert response.status_code == 401


def test_create_purchase_record_as_employee_succeeds(
    db_session, make_supplier, make_project, make_user, make_session
):
    supplier = make_supplier()
    project = make_project([])
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/purchase-records",
        json={
            "supplier_id": str(supplier.id),
            "raw_description": "Employee-created line",
            "quantity": 1,
            "unit_price": 5.0,
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
