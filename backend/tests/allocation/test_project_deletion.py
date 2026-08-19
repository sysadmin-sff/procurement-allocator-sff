"""Tests for cascading Project deletion — ADR-0009.

Covers: cascade across PurchaseRecord/Order+OrderItem/AllocationRun+
AllocationLine/ProjectItem, the 409 refusal when any Order has left draft
status, that draft-only orders don't block deletion, and 404s.
"""

import uuid

from fastapi.testclient import TestClient

from app.allocation.order_service import create_orders_for_run
from app.allocation.service import run_allocation
from app.main import app
from app.models import (
    AllocationLine,
    AllocationRun,
    Order,
    OrderItem,
    Project,
    ProjectItem,
    PurchaseRecord,
)
from app.purchase_records.service import create_purchase_record

client = TestClient(app)


def test_delete_project_removes_it(db_session, make_project):
    session, project_ids, *_ = db_session
    project = make_project([])
    project_id = project.id
    project_ids.remove(project_id)  # already gone after delete — nothing left for cleanup

    response = client.delete(f"/projects/{project_id}")

    assert response.status_code == 204
    session.expire_all()  # the row was deleted by a separate bulk delete() call
    assert session.get(Project, project_id) is None


def test_delete_project_returns_404_for_unknown_project():
    response = client.delete(f"/projects/{uuid.uuid4()}")

    assert response.status_code == 404


def test_delete_project_cascades_project_items(db_session, make_project, make_material):
    session, project_ids, *_ = db_session
    material = make_material()
    project = make_project([(material, 5)])
    project_id = project.id
    project_ids.remove(project_id)

    response = client.delete(f"/projects/{project_id}")

    assert response.status_code == 204
    assert session.query(ProjectItem).filter_by(project_id=project_id).count() == 0


def test_delete_project_cascades_allocation_run_and_lines(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, project_ids, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    project_id = project.id
    project_ids.remove(project_id)

    run = run_allocation(session, project_id)
    run_id = run.id
    assert session.query(AllocationLine).filter_by(allocation_run_id=run_id).count() == 1

    response = client.delete(f"/projects/{project_id}")

    assert response.status_code == 204
    assert session.get(AllocationRun, run_id) is None
    assert session.query(AllocationLine).filter_by(allocation_run_id=run_id).count() == 0


def test_delete_project_cascades_draft_orders(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, project_ids, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    project_id = project.id
    project_ids.remove(project_id)

    run = run_allocation(session, project_id)
    orders = create_orders_for_run(session, project_id, run.id)
    assert orders[0].status == "draft"
    order_id = orders[0].id
    item_id = orders[0].items[0].id

    response = client.delete(f"/projects/{project_id}")

    assert response.status_code == 204
    assert session.get(Order, order_id) is None
    assert session.get(OrderItem, item_id) is None


def test_delete_project_cascades_purchase_records(db_session, make_supplier, make_project):
    session, project_ids, *_ = db_session
    supplier = make_supplier()
    project = make_project([])
    project_id = project.id
    project_ids.remove(project_id)

    record = create_purchase_record(
        session,
        project_id=project_id,
        supplier_id=supplier.id,
        raw_description="X",
        quantity=1,
        unit_price=1.0,
        material_id=None,
    )
    record_id = record.id

    response = client.delete(f"/projects/{project_id}")

    assert response.status_code == 204
    assert session.get(PurchaseRecord, record_id) is None


def test_delete_project_refuses_when_order_is_sent(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, project_ids, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    project_id = project.id

    run = run_allocation(session, project_id)
    orders = create_orders_for_run(session, project_id, run.id)
    orders[0].status = "sent"
    session.commit()

    response = client.delete(f"/projects/{project_id}")

    assert response.status_code == 409
    assert session.get(Project, project_id) is not None


def test_delete_project_refuses_when_order_is_approved(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, project_ids, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    project_id = project.id

    run = run_allocation(session, project_id)
    orders = create_orders_for_run(session, project_id, run.id)
    orders[0].status = "approved"
    session.commit()

    response = client.delete(f"/projects/{project_id}")

    assert response.status_code == 409


def test_delete_project_refusal_does_not_touch_other_data(
    db_session, make_supplier, make_material, make_price, make_project
):
    """A refused delete must not partially remove anything — not the Order,
    not the AllocationRun, not the project itself. See ADR-0009 п.1."""
    session, project_ids, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    project_id = project.id

    run = run_allocation(session, project_id)
    orders = create_orders_for_run(session, project_id, run.id)
    orders[0].status = "sent"
    session.commit()
    order_id = orders[0].id
    run_id = run.id

    response = client.delete(f"/projects/{project_id}")

    assert response.status_code == 409
    assert session.get(Project, project_id) is not None
    assert session.get(Order, order_id) is not None
    assert session.get(AllocationRun, run_id) is not None
    assert session.query(ProjectItem).filter_by(project_id=project_id).count() == 1


def test_delete_project_with_only_draft_orders_across_multiple_suppliers(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, project_ids, *_ = db_session
    supplier_a = make_supplier(name="A", flat_fee=0.0, free_shipping_threshold=0.0)
    supplier_b = make_supplier(name="B", flat_fee=0.0, free_shipping_threshold=1000.0)
    material_a = make_material()
    material_b = make_material()
    make_price(material_a, supplier_a, price=5.00, availability=10)
    make_price(material_b, supplier_b, price=6.00, availability=10)
    project = make_project([(material_a, 1), (material_b, 1)])
    project_id = project.id
    project_ids.remove(project_id)

    run = run_allocation(session, project_id)
    orders = create_orders_for_run(session, project_id, run.id)
    assert len(orders) == 2
    assert all(o.status == "draft" for o in orders)

    response = client.delete(f"/projects/{project_id}")

    assert response.status_code == 204
    assert session.query(Order).filter_by(project_id=project_id).count() == 0
