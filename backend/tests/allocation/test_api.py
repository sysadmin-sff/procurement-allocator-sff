import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.models import Project

CSRF = "test-csrf-token"
_employee_email_counter = [0]


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def _employee_client(make_user, make_session):
    _employee_email_counter[0] += 1
    email = f"employee-allocation-api{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session)


def test_allocate_returns_run_with_lines(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    client = _employee_client(make_user, make_session)

    response = client.post(f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == str(project.id)
    assert body["status"] == "ok"
    assert body["orphaned_materials"] == []
    assert len(body["lines"]) == 1
    line = body["lines"][0]
    assert line["material_id"] == str(material.id)
    assert line["supplier_id"] == str(supplier.id)
    assert line["quantity"] == 10
    assert line["unit_price"] == 5.00
    assert line["line_total"] == 50.00


def test_get_project_reflects_latest_allocation_run(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    client = _employee_client(make_user, make_session)

    before_allocate = client.get(f"/projects/{project.id}")
    assert before_allocate.json()["latest_allocation_run"] is None

    allocate_response = client.post(
        f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF}
    )
    run_id = allocate_response.json()["id"]

    after_allocate = client.get(f"/projects/{project.id}")
    latest_run = after_allocate.json()["latest_allocation_run"]
    assert latest_run["id"] == run_id
    assert latest_run["status"] == "ok"


def test_allocate_returns_infeasible_status_when_sole_supplier_misses_min_order_amount(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """API-level counterpart to the service-level regression in
    test_service.py — status must be visible in AllocationRunOut on both
    POST (create) and GET (fetch persisted run). See ADR-0003."""
    session, *_ = db_session
    supplier = make_supplier(
        name="Gated Sole Supplier",
        flat_fee=0.0,
        free_shipping_threshold=0.0,
        per_order_min_amount=200.0,
    )
    material = make_material()
    make_price(material, supplier, price=13.25, availability=500)
    project = make_project([(material, 10)])  # 132.50, below the $200 minimum
    client = _employee_client(make_user, make_session)

    post_response = client.post(
        f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF}
    )

    assert post_response.status_code == 200
    post_body = post_response.json()
    assert post_body["status"] == "infeasible"
    assert post_body["lines"] == []
    assert post_body["supplier_summaries"] == []

    run_id = post_body["id"]
    get_response = client.get(f"/projects/{project.id}/allocations/{run_id}")

    assert get_response.status_code == 200
    get_body = get_response.json()
    assert get_body["status"] == "infeasible"
    assert get_body["lines"] == []
    assert get_body["supplier_summaries"] == []


def test_allocate_includes_orphaned_materials_in_response(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    orphaned_material = make_material()
    make_price(orphaned_material, supplier, price=3.00, availability=2)
    project = make_project([(orphaned_material, 10)])
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF}
    )

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
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=10.0, free_shipping_threshold=1000.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 1)])
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["supplier_summaries"]) == 1
    summary = body["supplier_summaries"][0]
    assert summary["supplier_id"] == str(supplier.id)
    assert summary["goods_total"] == 5.00
    assert summary["delivery_fee"] == 10.00
    assert summary["free_shipping_achieved"] is False


def test_allocate_includes_tax_amount_in_supplier_summary_response(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """ADR-0029 §5а: tax_amount/total_with_tax must be exposed through
    SupplierAllocationSummaryOut, not just present in the internal JSON
    dict — the Pydantic schema would silently drop an unlisted field."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=10.0, free_shipping_threshold=1000.0)
    material = make_material()
    make_price(material, supplier, price=100.00, availability=10)
    project = make_project([(material, 1)])
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF}
    )

    summary = response.json()["supplier_summaries"][0]
    assert summary["tax_amount"] == 7.00
    assert summary["total_with_tax"] == 117.00


def test_allocate_includes_split_categories_in_response(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """ADR-0028 §4: split_categories must be exposed on the API response, not
    just persisted internally — the frontend warning depends on it."""
    session, *_ = db_session
    s1 = make_supplier(name="Supplier One", flat_fee=0.0, free_shipping_threshold=0.0)
    s2 = make_supplier(name="Supplier Two", flat_fee=0.0, free_shipping_threshold=0.0)
    mesh1 = make_material(category="Mesh")
    mesh2 = make_material(category="Mesh")
    make_price(mesh1, s1, price=5.00, availability=10)
    make_price(mesh2, s2, price=6.00, availability=10)
    project = make_project([(mesh1, 1), (mesh2, 1)])
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 200
    assert response.json()["split_categories"] == ["Mesh"]


def test_allocate_returns_404_for_nonexistent_project(make_user, make_session):
    client = _employee_client(make_user, make_session)
    response = client.post(
        f"/projects/{uuid.uuid4()}/allocate", headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 404


def test_allocate_returns_400_for_project_with_no_items(db_session, make_user, make_session):
    session, project_ids, *_ = db_session
    project = Project(title="Empty Project", status="draft")
    session.add(project)
    session.commit()
    project_ids.append(project.id)
    client = _employee_client(make_user, make_session)

    response = client.post(f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 400


def test_get_allocation_run_returns_persisted_result(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    client = _employee_client(make_user, make_session)

    create_response = client.post(
        f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF}
    )
    run_id = create_response.json()["id"]

    get_response = client.get(f"/projects/{project.id}/allocations/{run_id}")

    assert get_response.status_code == 200
    assert get_response.json() == create_response.json()


def test_get_allocation_run_returns_404_for_unknown_run(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 1)])
    client = _employee_client(make_user, make_session)

    response = client.get(f"/projects/{project.id}/allocations/{uuid.uuid4()}")

    assert response.status_code == 404


def test_get_allocation_run_returns_404_when_run_belongs_to_different_project(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project_a = make_project([(material, 10)])
    project_b = make_project([(material, 10)])
    client = _employee_client(make_user, make_session)

    run_response = client.post(
        f"/projects/{project_a.id}/allocate", headers={"X-CSRF-Token": CSRF}
    )
    run_id = run_response.json()["id"]

    response = client.get(f"/projects/{project_b.id}/allocations/{run_id}")

    assert response.status_code == 404


def test_patch_override_line_supplier_returns_updated_line(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    old_supplier = make_supplier(name="Old Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    new_supplier = make_supplier(name="New Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, old_supplier, price=5.00, availability=10)
    make_price(material, new_supplier, price=7.00, availability=10)
    project = make_project([(material, 10)])
    client = _employee_client(make_user, make_session)

    run_response = client.post(f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF})
    run_id = run_response.json()["id"]
    line_id = run_response.json()["lines"][0]["id"]

    response = client.patch(
        f"/projects/{project.id}/allocations/{run_id}/lines/{line_id}",
        json={"supplier_id": str(new_supplier.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["supplier_id"] == str(new_supplier.id)
    assert body["unit_price"] == 7.00
    assert body["line_total"] == 70.00
    assert body["overridden_at"] is not None
    assert body["original_supplier_id"] == str(old_supplier.id)
    assert body["original_unit_price"] == 5.00


def test_patch_override_line_supplier_persists_across_get(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """The override must survive re-fetching the run — not just be reflected
    in the PATCH response — since it's backend-persisted, not client state.
    See ADR-0006 п.5 (ADR-0004 F5-loss class of bug)."""
    session, *_ = db_session
    old_supplier = make_supplier(name="Old Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    new_supplier = make_supplier(name="New Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, old_supplier, price=5.00, availability=10)
    make_price(material, new_supplier, price=7.00, availability=10)
    project = make_project([(material, 10)])
    client = _employee_client(make_user, make_session)

    run_response = client.post(f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF})
    run_id = run_response.json()["id"]
    line_id = run_response.json()["lines"][0]["id"]

    client.patch(
        f"/projects/{project.id}/allocations/{run_id}/lines/{line_id}",
        json={"supplier_id": str(new_supplier.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    get_response = client.get(f"/projects/{project.id}/allocations/{run_id}")
    body = get_response.json()
    line = next(entry for entry in body["lines"] if entry["id"] == line_id)
    assert line["supplier_id"] == str(new_supplier.id)
    assert line["overridden_at"] is not None

    summaries = {s["supplier_id"]: s for s in body["supplier_summaries"]}
    assert str(old_supplier.id) not in summaries
    assert summaries[str(new_supplier.id)]["goods_total"] == 70.00


def test_patch_override_returns_422_for_supplier_without_active_price(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    old_supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    supplier_without_price = make_supplier(
        name="No Price Supplier", flat_fee=0.0, free_shipping_threshold=0.0
    )
    material = make_material()
    make_price(material, old_supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    client = _employee_client(make_user, make_session)

    run_response = client.post(f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF})
    run_id = run_response.json()["id"]
    line_id = run_response.json()["lines"][0]["id"]

    response = client.patch(
        f"/projects/{project.id}/allocations/{run_id}/lines/{line_id}",
        json={"supplier_id": str(supplier_without_price.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_patch_override_returns_404_for_unknown_line(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    client = _employee_client(make_user, make_session)

    run_response = client.post(f"/projects/{project.id}/allocate", headers={"X-CSRF-Token": CSRF})
    run_id = run_response.json()["id"]

    response = client.patch(
        f"/projects/{project.id}/allocations/{run_id}/lines/{uuid.uuid4()}",
        json={"supplier_id": str(supplier.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_patch_override_returns_404_when_run_belongs_to_different_project(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project_a = make_project([(material, 10)])
    project_b = make_project([(material, 10)])
    client = _employee_client(make_user, make_session)

    run_response = client.post(
        f"/projects/{project_a.id}/allocate", headers={"X-CSRF-Token": CSRF}
    )
    run_id = run_response.json()["id"]
    line_id = run_response.json()["lines"][0]["id"]

    response = client.patch(
        f"/projects/{project_b.id}/allocations/{run_id}/lines/{line_id}",
        json={"supplier_id": str(supplier.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404
