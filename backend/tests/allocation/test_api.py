import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.models import Project

client = TestClient(app)


def test_allocate_returns_run_with_lines(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    response = client.post(f"/projects/{project.id}/allocate")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == str(project.id)
    assert body["orphaned_materials"] == []
    assert len(body["lines"]) == 1
    line = body["lines"][0]
    assert line["material_id"] == str(material.id)
    assert line["supplier_id"] == str(supplier.id)
    assert line["quantity"] == 10
    assert line["unit_price"] == 5.00
    assert line["line_total"] == 50.00


def test_allocate_includes_orphaned_materials_in_response(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    orphaned_material = make_material()
    make_price(orphaned_material, supplier, price=3.00, availability=2)
    project = make_project([(orphaned_material, 10)])

    response = client.post(f"/projects/{project.id}/allocate")

    assert response.status_code == 200
    body = response.json()
    assert body["lines"] == []
    assert len(body["orphaned_materials"]) == 1
    orphaned = body["orphaned_materials"][0]
    assert orphaned["material_id"] == str(orphaned_material.id)
    assert orphaned["required_quantity"] == 10
    assert orphaned["best_partial_supplier_id"] == str(supplier.id)
    assert orphaned["best_partial_available"] == 2


def test_allocate_includes_supplier_summaries_in_response(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=10.0, free_shipping_threshold=1000.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 1)])

    response = client.post(f"/projects/{project.id}/allocate")

    assert response.status_code == 200
    body = response.json()
    assert len(body["supplier_summaries"]) == 1
    summary = body["supplier_summaries"][0]
    assert summary["supplier_id"] == str(supplier.id)
    assert summary["goods_total"] == 5.00
    assert summary["delivery_fee"] == 10.00
    assert summary["free_shipping_achieved"] is False


def test_allocate_returns_404_for_nonexistent_project():
    response = client.post(f"/projects/{uuid.uuid4()}/allocate")

    assert response.status_code == 404


def test_allocate_returns_400_for_project_with_no_items(db_session):
    session, project_ids, *_ = db_session
    project = Project(title="Empty Project", status="draft")
    session.add(project)
    session.commit()
    project_ids.append(project.id)

    response = client.post(f"/projects/{project.id}/allocate")

    assert response.status_code == 400


def test_get_allocation_run_returns_persisted_result(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    create_response = client.post(f"/projects/{project.id}/allocate")
    run_id = create_response.json()["id"]

    get_response = client.get(f"/projects/{project.id}/allocations/{run_id}")

    assert get_response.status_code == 200
    assert get_response.json() == create_response.json()


def test_get_allocation_run_returns_404_for_unknown_run(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 1)])

    response = client.get(f"/projects/{project.id}/allocations/{uuid.uuid4()}")

    assert response.status_code == 404


def test_get_allocation_run_returns_404_when_run_belongs_to_different_project(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project_a = make_project([(material, 10)])
    project_b = make_project([(material, 10)])

    run_response = client.post(f"/projects/{project_a.id}/allocate")
    run_id = run_response.json()["id"]

    response = client.get(f"/projects/{project_b.id}/allocations/{run_id}")

    assert response.status_code == 404
