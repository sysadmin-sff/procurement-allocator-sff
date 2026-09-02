"""Tests for POST /orders/{order_id}/items/{item_id}/replace-and-order —
ADR-0015. Covers replace_and_sync_order() (backend/app/allocation/
order_service.py): override + Order/OrderItem sync in one transaction, the
409 conflicts (multiple existing drafts, duplicate material_id in the target
draft) rolling back the override, and the regression that the plain
PATCH .../lines/{line_id} (ADR-0006/ADR-0014, no source_order_item_id) is
unaffected by this endpoint's existence.
"""

from fastapi.testclient import TestClient

from app.allocation.order_service import create_orders_for_run, set_order_item_fields
from app.allocation.service import run_allocation
from app.main import app
from app.models import AllocationLine, Order

CSRF = "test-csrf-token"
_employee_email_counter = [0]


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def _employee_client(make_user, make_session):
    _employee_email_counter[0] += 1
    email = f"employee-replace-and-order{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session)


def _declined_item(session, make_supplier, make_material, make_price, make_project):
    """Same fixture shape as test_find_replacement.py's _declined_item: one
    material, one supplier, a draft Order with its single item declined."""
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


def _line_for(session, run_id, material_id):
    return (
        session.query(AllocationLine)
        .filter_by(allocation_run_id=run_id, material_id=material_id)
        .one()
    )


# --- no existing draft for the new supplier -> creates a new Order ---


def test_creates_new_order_when_no_existing_draft(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    candidate = make_supplier(name="Fresh Candidate", flat_fee=2.50, free_shipping_threshold=0.0)
    make_price(material, candidate, price=6.00, availability=10)
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/{item.id}/replace-and-order",
        json={"supplier_id": str(candidate.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["replaced_by_supplier_id"] == str(candidate.id)
    assert body["replacement_draft_order_id"] is not None

    new_order = session.get(Order, body["replacement_draft_order_id"])
    assert new_order.supplier_id == candidate.id
    assert new_order.status == "draft"
    assert len(new_order.items) == 1
    new_item = new_order.items[0]
    assert new_item.material_id == material.id
    assert new_item.quantity == 10
    assert float(new_item.quoted_price) == 6.00

    run_out = session.get(type(run), run.id)
    summary = next(s for s in run_out.supplier_summaries if s["supplier_id"] == str(candidate.id))
    assert float(new_order.total_amount) == summary["goods_total"]
    assert float(new_order.delivery_fee) == summary["delivery_fee"]

    line = _line_for(session, run.id, material.id)
    assert line.supplier_id == candidate.id
    assert line.overridden_via_order_item_id == item.id


# --- exactly one existing draft for the new supplier -> item added to it ---


def test_adds_to_single_existing_draft_without_touching_other_items(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )

    candidate = make_supplier(name="Candidate", flat_fee=0.0, free_shipping_threshold=0.0)
    other_material = make_material()
    make_price(other_material, candidate, price=3.00, availability=10)
    make_price(material, candidate, price=6.00, availability=10)

    from app.models import ProjectItem

    session.add(ProjectItem(project_id=project.id, material_id=other_material.id, quantity=4))
    session.commit()
    other_run = run_allocation(session, project.id)
    other_orders = create_orders_for_run(session, project.id, other_run.id, replace_drafts=True)
    candidate_draft = next(o for o in other_orders if o.supplier_id == candidate.id)
    existing_item = candidate_draft.items[0]
    existing_item.confirmed_price = 2.75
    existing_item.received_price = 2.80
    session.commit()

    # Re-fetch the declined item's order after create_orders_for_run(replace_drafts=True)
    # recreated the declining supplier's draft too.
    declining_order = next(o for o in other_orders if o.supplier_id == _declining.id)
    item = declining_order.items[0]
    set_order_item_fields(session, declining_order.id, item.id, declined=True)
    order = declining_order
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/{item.id}/replace-and-order",
        json={"supplier_id": str(candidate.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["replacement_draft_order_id"] == str(candidate_draft.id)

    session.refresh(candidate_draft)
    assert len(candidate_draft.items) == 2
    kept = next(i for i in candidate_draft.items if i.id == existing_item.id)
    assert float(kept.confirmed_price) == 2.75
    assert float(kept.received_price) == 2.80
    new_item = next(i for i in candidate_draft.items if i.id != existing_item.id)
    assert new_item.material_id == material.id
    assert float(new_item.quoted_price) == 6.00

    run_out = session.get(type(other_run), other_run.id)
    summary = next(
        s for s in run_out.supplier_summaries if s["supplier_id"] == str(candidate.id)
    )
    assert float(candidate_draft.total_amount) == summary["goods_total"]
    assert float(candidate_draft.delivery_fee) == summary["delivery_fee"]


# --- duplicate material_id already in target draft -> 409, override not applied ---


def test_duplicate_material_in_target_draft_returns_409_and_does_not_override(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    candidate = make_supplier(name="Candidate", flat_fee=0.0, free_shipping_threshold=0.0)
    make_price(material, candidate, price=6.00, availability=10)

    line_before = _line_for(session, run.id, material.id)
    original_supplier_id = line_before.supplier_id

    # Give candidate an existing draft that already has an OrderItem for the
    # same material (simulated directly rather than via a second run, since
    # the point is just "this material_id is already in that draft").
    from app.models import OrderItem

    existing_draft = Order(
        project_id=project.id,
        supplier_id=candidate.id,
        status="draft",
        total_amount=6.00,
        delivery_fee=0.0,
    )
    session.add(existing_draft)
    session.flush()
    session.add(
        OrderItem(
            order_id=existing_draft.id,
            material_id=material.id,
            quantity=1,
            quoted_price=6.00,
        )
    )
    session.commit()
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/{item.id}/replace-and-order",
        json={"supplier_id": str(candidate.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409

    session.refresh(line_before)
    assert line_before.supplier_id == original_supplier_id
    assert line_before.overridden_via_order_item_id is None
    session.refresh(existing_draft)
    assert len(existing_draft.items) == 1


# --- more than one existing draft for the new supplier -> 409, override not applied ---


def test_multiple_existing_drafts_returns_409_and_does_not_override(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    candidate = make_supplier(name="Candidate", flat_fee=0.0, free_shipping_threshold=0.0)
    make_price(material, candidate, price=6.00, availability=10)

    line_before = _line_for(session, run.id, material.id)
    original_supplier_id = line_before.supplier_id

    dup_a = Order(
        project_id=project.id, supplier_id=candidate.id, status="draft",
        total_amount=1.0, delivery_fee=0.0,
    )
    dup_b = Order(
        project_id=project.id, supplier_id=candidate.id, status="draft",
        total_amount=1.0, delivery_fee=0.0,
    )
    session.add_all([dup_a, dup_b])
    session.commit()
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/{item.id}/replace-and-order",
        json={"supplier_id": str(candidate.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409

    session.refresh(line_before)
    assert line_before.supplier_id == original_supplier_id
    assert line_before.overridden_via_order_item_id is None

    remaining = session.query(Order).filter_by(supplier_id=candidate.id).all()
    assert len(remaining) == 2
    assert all(o.status == "draft" for o in remaining)
    assert all(len(o.items) == 0 for o in remaining)


# --- material missing from latest run -> 404 (ADR-0014 regression) ---


def test_material_missing_from_latest_run_returns_404(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    candidate = make_supplier(name="Candidate", flat_fee=0.0, free_shipping_threshold=0.0)
    make_price(material, candidate, price=6.00, availability=10)

    session.query(AllocationLine).filter_by(allocation_run_id=run.id).delete()
    session.commit()
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{order.id}/items/{item.id}/replace-and-order",
        json={"supplier_id": str(candidate.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


# --- regression: ADR-0026 fully_declined filter must not apply here (ADR-0015 §1) ---


def test_fully_declined_existing_draft_still_found_and_receives_new_item(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """ADR-0026 §2 explicit carve-out: the fully_declined-without-
    confirmed-prices filter added to _conflicting_draft_orders_by_supplier
    (ADR-0012) must NOT apply to replace_and_sync_order's own draft lookup
    (ADR-0015 §1 step 3). A candidate supplier's only existing draft, whose
    sole item is declined, must still be found as "the one existing draft"
    and receive the newly transferred item — not be treated as absent,
    which would create a second draft for the same supplier/project."""
    session, *_ = db_session
    _declining, material, project, run, order, item = _declined_item(
        session, make_supplier, make_material, make_price, make_project
    )
    candidate = make_supplier(
        name="Fully Declined Candidate", flat_fee=0.0, free_shipping_threshold=0.0
    )
    make_price(material, candidate, price=6.00, availability=10)

    other_material = make_material()
    make_price(other_material, candidate, price=3.00, availability=10)
    from app.models import ProjectItem

    session.add(ProjectItem(project_id=project.id, material_id=other_material.id, quantity=1))
    session.commit()
    seed_run = run_allocation(session, project.id)
    seed_orders = create_orders_for_run(session, project.id, seed_run.id, replace_drafts=True)
    candidate_draft = next(o for o in seed_orders if o.supplier_id == candidate.id)
    assert len(candidate_draft.items) == 1
    fully_declined_item_id = candidate_draft.items[0].id
    set_order_item_fields(session, candidate_draft.id, fully_declined_item_id, declined=True)

    declining_order = next(o for o in seed_orders if o.supplier_id == _declining.id)
    declining_item = declining_order.items[0]
    set_order_item_fields(session, declining_order.id, declining_item.id, declined=True)
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/orders/{declining_order.id}/items/{declining_item.id}/replace-and-order",
        json={"supplier_id": str(candidate.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    # Found (not ignored) -> the existing, fully-declined draft is reused, no new Order created.
    assert body["replacement_draft_order_id"] == str(candidate_draft.id)

    session.refresh(candidate_draft)
    assert len(candidate_draft.items) == 2
    still_declined = next(i for i in candidate_draft.items if i.id == fully_declined_item_id)
    assert still_declined.declined_at is not None  # untouched
    new_item = next(i for i in candidate_draft.items if i.id != fully_declined_item_id)
    assert new_item.material_id == material.id
    assert new_item.declined_at is None

    all_candidate_drafts = (
        session.query(Order)
        .filter_by(project_id=project.id, supplier_id=candidate.id, status="draft")
        .all()
    )
    assert len(all_candidate_drafts) == 1  # no second draft was created alongside it


# --- regression: plain PATCH .../lines/{line_id} (ADR-0006/ADR-0014) unaffected ---


def test_plain_patch_line_override_without_source_order_item_id_still_works(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    old_supplier = make_supplier(name="Old", flat_fee=0.0, free_shipping_threshold=0.0)
    new_supplier = make_supplier(name="New", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, old_supplier, price=5.00, availability=10)
    make_price(material, new_supplier, price=7.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    line = _line_for(session, run.id, material.id)
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/projects/{project.id}/allocations/{run.id}/lines/{line.id}",
        json={"supplier_id": str(new_supplier.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    session.refresh(line)
    assert line.supplier_id == new_supplier.id
    assert line.overridden_via_order_item_id is None
