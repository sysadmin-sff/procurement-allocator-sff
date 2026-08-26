"""Tests for the declined-OrderItem replacement flow — ADR-0014.

Covers: GET /materials/{material_id}/prices, POST
/orders/{order_id}/items/{item_id}/find-replacement, the
source_order_item_id extension to PATCH .../lines/{line_id}, and the
replaced_by_supplier_id/replaced_by_supplier_name/replacement_draft_order_id
derived fields on OrderItemOut.
"""

from fastapi.testclient import TestClient

from app.allocation.order_service import create_orders_for_run, set_order_item_fields
from app.allocation.service import override_allocation_line_supplier, run_allocation
from app.main import app
from app.models import AllocationLine

CSRF = "test-csrf-token"
_employee_email_counter = [0]


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def _employee_client(make_user, make_session):
    _employee_email_counter[0] += 1
    email = f"employee-find-replacement{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session)


def _declined_item(session, make_supplier, make_material, make_price, make_project):
    """Sets up a project with one material, one supplier, creates a draft
    Order and declines its single item — the common starting point for
    find-replacement tests."""
    supplier = make_supplier(name="Declining Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    order = orders[0]
    item = order.items[0]
    set_order_item_fields(session, order.id, item.id, declined=True, decline_reason="no stock")
    return supplier, material, project, run, order, item


# --- GET /materials/{material_id}/prices ---


def test_get_material_prices_returns_active_prices_across_suppliers(
    db_session, make_supplier, make_material, make_price, make_user, make_session
):
    session, *_ = db_session
    supplier_a = make_supplier(name="A")
    supplier_b = make_supplier(name="B")
    material = make_material()
    make_price(material, supplier_a, price=5.00, availability=10)
    make_price(material, supplier_b, price=7.00, availability=2)
    client = _employee_client(make_user, make_session)

    response = client.get(f"/materials/{material.id}/prices")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    supplier_ids = {p["supplier_id"] for p in body}
    assert supplier_ids == {str(supplier_a.id), str(supplier_b.id)}


def test_get_material_prices_excludes_closed_prices(
    db_session, make_supplier, make_material, make_price, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material()
    closed = make_price(material, supplier, price=5.00, availability=10)
    closed.valid_to = closed.valid_from
    session.flush()
    client = _employee_client(make_user, make_session)

    response = client.get(f"/materials/{material.id}/prices")

    assert response.status_code == 200
    assert response.json() == []


# --- POST /orders/{order_id}/items/{item_id}/find-replacement ---


def test_find_replacement_returns_candidates_with_prices_and_line_id(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    declining_supplier, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    candidate_supplier = make_supplier(
        name="Candidate", flat_fee=0.0, free_shipping_threshold=0.0
    )
    make_price(material, candidate_supplier, price=6.00, availability=10)
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/{item.id}/find-replacement",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()
    assert body["line_id"] == str(line.id)
    supplier_ids = {c["supplier_id"] for c in body["candidates"]}
    assert supplier_ids == {str(declining_supplier.id), str(candidate_supplier.id)}


def test_find_replacement_flags_availability_risk_when_explicitly_short(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    short_supplier = make_supplier(name="Short", flat_fee=0.0, free_shipping_threshold=0.0)
    make_price(material, short_supplier, price=6.00, availability=2)  # quantity is 10
    unknown_supplier = make_supplier(name="Unknown", flat_fee=0.0, free_shipping_threshold=0.0)
    make_price(material, unknown_supplier, price=8.00, availability=None)
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/{item.id}/find-replacement",
        headers={"X-CSRF-Token": CSRF},
    )

    candidates = {c["supplier_id"]: c for c in response.json()["candidates"]}
    assert candidates[str(short_supplier.id)]["availability_risk"] is True
    assert candidates[str(unknown_supplier.id)]["availability_risk"] is False


def test_find_replacement_returns_404_when_material_missing_from_latest_run(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    from app.models import AllocationLine as ALine

    session.query(ALine).filter_by(allocation_run_id=run.id).delete()
    session.commit()
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/{item.id}/find-replacement",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_find_replacement_uses_latest_run_not_the_run_that_created_the_order(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """The order was created from `run`, but a newer AllocationRun exists by
    the time find-replacement is called — п.2 requires searching the latest
    run, not the run that produced the Order."""
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    new_run = run_allocation(session, project.id)
    new_line = session.query(AllocationLine).filter_by(allocation_run_id=new_run.id).one()
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/{item.id}/find-replacement",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["line_id"] == str(new_line.id)


# --- PATCH .../lines/{line_id} with source_order_item_id ---


def test_patch_with_source_order_item_id_sets_attribution(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    candidate = make_supplier(name="Candidate", flat_fee=0.0, free_shipping_threshold=0.0)
    make_price(material, candidate, price=6.00, availability=10)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/projects/{project.id}/allocations/{run.id}/lines/{line.id}",
        json={"supplier_id": str(candidate.id), "source_order_item_id": str(item.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    session.refresh(line)
    assert line.overridden_via_order_item_id == item.id


def test_get_order_exposes_replaced_by_supplier_after_find_replacement_patch(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    candidate = make_supplier(name="Candidate", flat_fee=0.0, free_shipping_threshold=0.0)
    make_price(material, candidate, price=6.00, availability=10)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()
    client = _employee_client(make_user, make_session)

    client.patch(
        f"/projects/{project.id}/allocations/{run.id}/lines/{line.id}",
        json={"supplier_id": str(candidate.id), "source_order_item_id": str(item.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.get(f"/orders/{order.id}")

    declined_item_out = next(i for i in response.json()["items"] if i["id"] == str(item.id))
    assert declined_item_out["replaced_by_supplier_id"] == str(candidate.id)
    assert declined_item_out["replaced_by_supplier_name"] == "Candidate"


def test_patch_without_source_order_item_id_leaves_attribution_null(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """Regression: ordinary manual override from AllocationResultPage (no
    source_order_item_id) must not set overridden_via_order_item_id — old
    behavior (ADR-0006) unaffected."""
    session, *_ = db_session
    old_supplier = make_supplier(name="Old", flat_fee=0.0, free_shipping_threshold=0.0)
    new_supplier = make_supplier(name="New", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, old_supplier, price=5.00, availability=10)
    make_price(material, new_supplier, price=7.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/projects/{project.id}/allocations/{run.id}/lines/{line.id}",
        json={"supplier_id": str(new_supplier.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    session.refresh(line)
    assert line.overridden_via_order_item_id is None


def test_third_override_without_source_order_item_id_clears_attribution(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """Key ADR-0014 §3 scenario: a line was reassigned via find-replacement
    (attribution set), then reassigned again via an ordinary manual PATCH
    without source_order_item_id — attribution must reset to NULL, and
    replaced_by_supplier_id for the original declined item must become null
    on the next GET /orders/{id}."""
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    via_replacement = make_supplier(
        name="Via Replacement", flat_fee=0.0, free_shipping_threshold=0.0
    )
    make_price(material, via_replacement, price=6.00, availability=10)
    plain_override = make_supplier(
        name="Plain Override", flat_fee=0.0, free_shipping_threshold=0.0
    )
    make_price(material, plain_override, price=8.00, availability=10)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()
    client = _employee_client(make_user, make_session)

    client.patch(
        f"/projects/{project.id}/allocations/{run.id}/lines/{line.id}",
        json={"supplier_id": str(via_replacement.id), "source_order_item_id": str(item.id)},
        headers={"X-CSRF-Token": CSRF},
    )
    session.refresh(line)
    assert line.overridden_via_order_item_id == item.id  # sanity

    client.patch(
        f"/projects/{project.id}/allocations/{run.id}/lines/{line.id}",
        json={"supplier_id": str(plain_override.id)},
        headers={"X-CSRF-Token": CSRF},
    )
    session.refresh(line)
    assert line.overridden_via_order_item_id is None

    response = client.get(f"/orders/{order.id}")
    declined_item_out = next(i for i in response.json()["items"] if i["id"] == str(item.id))
    assert declined_item_out["replaced_by_supplier_id"] is None


# --- replacement_draft_order_id ---


def test_replacement_draft_order_id_points_to_existing_draft_for_new_supplier(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    other_material = make_material()
    candidate = make_supplier(name="Candidate", flat_fee=0.0, free_shipping_threshold=0.0)
    make_price(material, candidate, price=6.00, availability=10)
    make_price(other_material, candidate, price=3.00, availability=10)
    client = _employee_client(make_user, make_session)

    # Give candidate an existing draft Order in this same project, on a
    # second, unrelated material/line — so it doesn't touch the declining
    # supplier's existing draft (the one holding `item`).
    from app.models import ProjectItem

    session.add(ProjectItem(project_id=project.id, material_id=other_material.id, quantity=1))
    session.commit()
    run_for_draft = run_allocation(session, project.id)
    draft_line = (
        session.query(AllocationLine)
        .filter_by(allocation_run_id=run_for_draft.id, material_id=other_material.id)
        .one()
    )
    override_allocation_line_supplier(session, run_for_draft.id, draft_line.id, candidate.id)
    # Only the (already-drafted) declining-supplier's line collides; replace
    # it so create_orders_for_run doesn't 409 on that pre-existing conflict —
    # candidate's line goes through the normal path either way.
    draft_orders = create_orders_for_run(
        session, project.id, run_for_draft.id, replace_drafts=True
    )
    candidate_draft = next(o for o in draft_orders if o.supplier_id == candidate.id)

    # The original declined item's Order was deleted by replace_drafts=True
    # above (same supplier, same material) — re-fetch a fresh declined item
    # on the *new* draft for the declining supplier so `item` refers to a
    # live row for the rest of the test.
    declining_order = next(o for o in draft_orders if o.supplier_id == _declining.id)
    item = declining_order.items[0]
    set_order_item_fields(session, declining_order.id, item.id, declined=True)
    order = declining_order

    line = session.query(AllocationLine).filter_by(
        allocation_run_id=run_for_draft.id, material_id=material.id
    ).one()
    client.patch(
        f"/projects/{project.id}/allocations/{run_for_draft.id}/lines/{line.id}",
        json={"supplier_id": str(candidate.id), "source_order_item_id": str(item.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.get(f"/orders/{order.id}")
    declined_item_out = next(i for i in response.json()["items"] if i["id"] == str(item.id))
    assert declined_item_out["replacement_draft_order_id"] == str(candidate_draft.id)


def test_replacement_draft_order_id_null_when_new_supplier_has_no_draft(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    candidate = make_supplier(name="Fresh Candidate", flat_fee=0.0, free_shipping_threshold=0.0)
    make_price(material, candidate, price=6.00, availability=10)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()
    client = _employee_client(make_user, make_session)

    client.patch(
        f"/projects/{project.id}/allocations/{run.id}/lines/{line.id}",
        json={"supplier_id": str(candidate.id), "source_order_item_id": str(item.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.get(f"/orders/{order.id}")
    declined_item_out = next(i for i in response.json()["items"] if i["id"] == str(item.id))
    assert declined_item_out["replacement_draft_order_id"] is None
