"""Tests for the draft-Order recreation guard — ADR-0012.

Covers: conflict detection on Order creation when draft Orders already exist
for a supplier in the current run's supplier_summaries, the 409 response body
shape (list of existing_draft_orders per supplier, has_confirmed_prices per
entry), replace_drafts=True semantics (delete old draft Order/OrderItem then
recreate), per-supplier granularity, and approved/sent Orders never being
treated as conflicts.

Also covers the ADR-0012 follow-up (docs/known-issues.md, "дозаказ тому же
поставщику при уже существующем draft"): acknowledge_conflict=True creates
the additional Orders next to the existing drafts without deleting anything,
while the default path keeps returning 409 exactly as before.
"""

from fastapi.testclient import TestClient

from app.allocation.order_service import (
    DraftOrderConflictError,
    create_orders_for_run,
)
from app.allocation.service import run_allocation
from app.main import app
from app.models import AllocationLine, Order, OrderItem

CSRF = "test-csrf-token"
_employee_email_counter = [0]


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def _employee_client(make_user, make_session):
    _employee_email_counter[0] += 1
    email = f"employee-order-draft-conflict{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session)


def _setup_single_supplier_project(make_supplier, make_material, make_price, make_project):
    supplier = make_supplier(name="Solo Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    return supplier, material, project


def test_no_conflict_creates_orders_as_before(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)

    orders = create_orders_for_run(session, project.id, run.id)

    assert len(orders) == 1
    assert orders[0].supplier_id == supplier.id


def test_conflict_without_replace_drafts_raises_and_creates_nothing(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    create_orders_for_run(session, project.id, run.id)  # first draft order exists now

    run2 = run_allocation(session, project.id)
    try:
        create_orders_for_run(session, project.id, run2.id)
        raise AssertionError("expected DraftOrderConflictError")
    except DraftOrderConflictError as exc:
        conflicts = exc.suppliers_with_existing_drafts
        assert len(conflicts) == 1
        assert conflicts[0]["supplier_id"] == supplier.id
        assert len(conflicts[0]["existing_draft_orders"]) == 1

    all_orders = session.query(Order).filter_by(project_id=project.id).all()
    assert len(all_orders) == 1  # nothing new created, nothing deleted


def test_conflict_via_api_returns_409_with_body(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    client = _employee_client(make_user, make_session)
    client.post(
        f"/projects/{project.id}/allocations/{run.id}/orders",
        headers={"X-CSRF-Token": CSRF},
    )

    run2 = run_allocation(session, project.id)
    response = client.post(
        f"/projects/{project.id}/allocations/{run2.id}/orders",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "draft_orders_exist"
    suppliers = body["suppliers_with_existing_drafts"]
    assert len(suppliers) == 1
    assert suppliers[0]["supplier_id"] == str(supplier.id)
    assert suppliers[0]["supplier_name"] == "Solo Supplier"
    existing = suppliers[0]["existing_draft_orders"]
    assert isinstance(existing, list)
    assert len(existing) == 1
    assert existing[0]["has_confirmed_prices"] is False
    assert "order_id" in existing[0]
    assert "total_amount" in existing[0]


def test_conflict_flags_has_confirmed_prices_when_old_draft_item_confirmed(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    first_orders = create_orders_for_run(session, project.id, run.id)
    item_id = first_orders[0].items[0].id
    client = _employee_client(make_user, make_session)
    client.patch(
        f"/orders/{first_orders[0].id}/items/{item_id}",
        json={"confirmed_price": 5.50},
        headers={"X-CSRF-Token": CSRF},
    )

    run2 = run_allocation(session, project.id)
    response = client.post(
        f"/projects/{project.id}/allocations/{run2.id}/orders",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409
    suppliers = response.json()["suppliers_with_existing_drafts"]
    assert suppliers[0]["existing_draft_orders"][0]["has_confirmed_prices"] is True


def test_replace_drafts_true_deletes_old_and_creates_new(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    first_orders = create_orders_for_run(session, project.id, run.id)
    old_order_id = first_orders[0].id

    run2 = run_allocation(session, project.id)
    new_orders = create_orders_for_run(session, project.id, run2.id, replace_drafts=True)

    assert len(new_orders) == 1
    assert new_orders[0].id != old_order_id
    assert session.get(Order, old_order_id) is None
    remaining_items = session.query(OrderItem).filter_by(order_id=old_order_id).all()
    assert remaining_items == []
    all_orders = session.query(Order).filter_by(project_id=project.id).all()
    assert len(all_orders) == 1


def test_replace_drafts_only_touches_conflicting_supplier(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Supplier A has a pre-existing draft (conflict); Supplier B is new in
    this run (no conflict) — replace_drafts=True must only replace A's
    draft, B is created via the normal path untouched. See ADR-0012 п.3.

    Mirrors the ADR's own scenario: an override moves part of the BOM to a
    new supplier between calculations, so only the overridden-away supplier
    has history in this project.
    """
    session, *_ = db_session
    supplier_a = make_supplier(name="A", flat_fee=0.0, free_shipping_threshold=0.0)
    supplier_b = make_supplier(name="B", flat_fee=0.0, free_shipping_threshold=0.0)
    material_a = make_material()
    material_b = make_material()
    make_price(material_a, supplier_a, price=5.00, availability=10)
    make_price(material_b, supplier_a, price=6.00, availability=10)
    make_price(material_b, supplier_b, price=6.00, availability=10)

    project = make_project([(material_a, 1), (material_b, 1)])

    # First run: both materials land on supplier A (cheapest/only option for
    # material_a, tied for material_b) -> a single Order for A only.
    run0 = run_allocation(session, project.id)
    first_orders = create_orders_for_run(session, project.id, run0.id)
    assert {o.supplier_id for o in first_orders} == {supplier_a.id}

    # Second run: override material_b's line onto supplier B, so this run's
    # supplier_summaries now has both A (pre-existing draft) and B (new).
    from app.allocation.service import override_allocation_line_supplier
    from app.models import AllocationLine

    run1 = run_allocation(session, project.id)
    line_b = (
        session.query(AllocationLine)
        .filter_by(allocation_run_id=run1.id, material_id=material_b.id)
        .one()
    )
    override_allocation_line_supplier(session, run1.id, line_b.id, supplier_b.id)

    old_order_id = first_orders[0].id
    new_orders = create_orders_for_run(session, project.id, run1.id, replace_drafts=True)

    suppliers_created = {o.supplier_id for o in new_orders}
    assert suppliers_created == {supplier_a.id, supplier_b.id}
    assert session.get(Order, old_order_id) is None  # A's old draft replaced

    b_order = next(o for o in new_orders if o.supplier_id == supplier_b.id)
    assert b_order.items[0].material_id == material_b.id


def test_replace_drafts_true_but_conflict_already_gone_is_not_an_error(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)

    orders = create_orders_for_run(session, project.id, run.id, replace_drafts=True)

    assert len(orders) == 1


def test_supplier_with_two_existing_drafts_both_listed_and_both_deleted(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    create_orders_for_run(session, project.id, run.id)
    run_dup = run_allocation(session, project.id)
    try:
        create_orders_for_run(session, project.id, run_dup.id)
    except DraftOrderConflictError:
        pass
    # Force a second draft directly (simulating the pre-ADR-0012 duplicate-bug state).
    dup_orders_before = session.query(Order).filter_by(project_id=project.id).all()
    assert len(dup_orders_before) == 1
    line = (
        session.query(AllocationLine)
        .filter_by(allocation_run_id=run_dup.id)
        .first()
    )
    second_draft = Order(
        project_id=project.id,
        supplier_id=supplier.id,
        status="draft",
        total_amount=float(line.line_total),
        delivery_fee=0.0,
    )
    session.add(second_draft)
    session.flush()
    session.add(
        OrderItem(
            order_id=second_draft.id,
            material_id=line.material_id,
            quantity=line.quantity,
            quoted_price=line.unit_price,
        )
    )
    session.commit()

    run3 = run_allocation(session, project.id)
    try:
        create_orders_for_run(session, project.id, run3.id)
        raise AssertionError("expected DraftOrderConflictError")
    except DraftOrderConflictError as exc:
        conflicts = exc.suppliers_with_existing_drafts
        assert len(conflicts) == 1
        assert len(conflicts[0]["existing_draft_orders"]) == 2

    new_orders = create_orders_for_run(session, project.id, run3.id, replace_drafts=True)
    assert len(new_orders) == 1
    remaining_drafts = (
        session.query(Order)
        .filter_by(project_id=project.id, supplier_id=supplier.id, status="draft")
        .all()
    )
    assert len(remaining_drafts) == 1
    assert remaining_drafts[0].id == new_orders[0].id


def test_approved_or_sent_orders_never_conflict_or_get_deleted(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    sent_orders = create_orders_for_run(session, project.id, run.id)
    sent_order = sent_orders[0]
    sent_order.status = "sent"
    session.commit()
    sent_order_id = sent_order.id

    run2 = run_allocation(session, project.id)
    # No draft conflict (the only existing Order is "sent") -> normal creation.
    new_orders = create_orders_for_run(session, project.id, run2.id)

    assert len(new_orders) == 1
    assert session.get(Order, sent_order_id) is not None  # untouched
    assert session.get(Order, sent_order_id).status == "sent"

    # Now also try replace_drafts=True with a real draft conflict alongside
    # the sent order — the sent order must survive regardless.
    run3 = run_allocation(session, project.id)
    replaced_orders = create_orders_for_run(session, project.id, run3.id, replace_drafts=True)
    assert len(replaced_orders) == 1
    assert session.get(Order, sent_order_id) is not None
    assert session.get(Order, sent_order_id).status == "sent"


def test_acknowledge_conflict_creates_alongside_and_keeps_old_drafts(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Follow-up to ADR-0012 (docs/known-issues.md): conflict +
    acknowledge_conflict=True is the "создать дополнительно" path — the new
    Orders are created as in the no-conflict case and the pre-existing draft
    survives untouched next to them, unlike replace_drafts=True which
    deletes it."""
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    first_orders = create_orders_for_run(session, project.id, run.id)
    old_order_id = first_orders[0].id
    old_item_ids = {item.id for item in first_orders[0].items}

    run2 = run_allocation(session, project.id)
    new_orders = create_orders_for_run(
        session, project.id, run2.id, acknowledge_conflict=True
    )

    assert len(new_orders) == 1
    assert new_orders[0].id != old_order_id
    assert new_orders[0].supplier_id == supplier.id

    old_order = session.get(Order, old_order_id)
    assert old_order is not None  # nothing deleted
    assert old_order.status == "draft"
    assert {item.id for item in old_order.items} == old_item_ids

    drafts = (
        session.query(Order)
        .filter_by(project_id=project.id, supplier_id=supplier.id, status="draft")
        .all()
    )
    assert {o.id for o in drafts} == {old_order_id, new_orders[0].id}


def test_acknowledge_conflict_keeps_confirmed_prices_on_old_draft(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """The reason this path exists at all (docs/known-issues.md follow-up):
    replacing a draft that already carries confirmed_price is an irreversible
    loss of manual work. The additional-order path must leave those values
    exactly where they were."""
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    first_orders = create_orders_for_run(session, project.id, run.id)
    old_order_id = first_orders[0].id
    old_item_id = first_orders[0].items[0].id
    client = _employee_client(make_user, make_session)
    client.patch(
        f"/orders/{old_order_id}/items/{old_item_id}",
        json={"confirmed_price": 5.50},
        headers={"X-CSRF-Token": CSRF},
    )

    run2 = run_allocation(session, project.id)
    response = client.post(
        f"/projects/{project.id}/allocations/{run2.id}/orders",
        json={"acknowledge_conflict": True},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    session.expire_all()
    old_item = session.get(OrderItem, old_item_id)
    assert old_item is not None
    assert float(old_item.confirmed_price) == 5.50


def test_acknowledge_conflict_via_api_returns_201(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    client = _employee_client(make_user, make_session)
    first = client.post(
        f"/projects/{project.id}/allocations/{run.id}/orders",
        headers={"X-CSRF-Token": CSRF},
    )
    assert first.status_code == 201
    old_order_id = first.json()[0]["id"]

    run2 = run_allocation(session, project.id)
    conflicted = client.post(
        f"/projects/{project.id}/allocations/{run2.id}/orders",
        headers={"X-CSRF-Token": CSRF},
    )
    assert conflicted.status_code == 409

    # Same request, now with the explicit acknowledgement the modal will send.
    response = client.post(
        f"/projects/{project.id}/allocations/{run2.id}/orders",
        json={"acknowledge_conflict": True},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    created = response.json()
    assert len(created) == 1
    assert created[0]["id"] != old_order_id
    assert created[0]["supplier_id"] == str(supplier.id)

    listed = client.get(f"/projects/{project.id}/orders").json()
    assert {o["id"] for o in listed} == {old_order_id, created[0]["id"]}


def test_conflict_without_acknowledge_conflict_still_409(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """Regression on ADR-0012's current behaviour: the new field must not
    weaken the default path. Both "field omitted" and explicit false still
    get the 409, and still create/delete nothing."""
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    client = _employee_client(make_user, make_session)
    client.post(
        f"/projects/{project.id}/allocations/{run.id}/orders",
        headers={"X-CSRF-Token": CSRF},
    )

    run2 = run_allocation(session, project.id)
    omitted = client.post(
        f"/projects/{project.id}/allocations/{run2.id}/orders",
        headers={"X-CSRF-Token": CSRF},
    )
    explicit_false = client.post(
        f"/projects/{project.id}/allocations/{run2.id}/orders",
        json={"acknowledge_conflict": False},
        headers={"X-CSRF-Token": CSRF},
    )
    both_false = client.post(
        f"/projects/{project.id}/allocations/{run2.id}/orders",
        json={"replace_drafts": False, "acknowledge_conflict": False},
        headers={"X-CSRF-Token": CSRF},
    )

    for response in (omitted, explicit_false, both_false):
        assert response.status_code == 409
        assert response.json()["detail"] == "draft_orders_exist"

    all_orders = session.query(Order).filter_by(project_id=project.id).all()
    assert len(all_orders) == 1  # nothing created, nothing deleted


def test_acknowledge_conflict_false_at_service_level_still_raises(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    create_orders_for_run(session, project.id, run.id)

    run2 = run_allocation(session, project.id)
    try:
        create_orders_for_run(session, project.id, run2.id, acknowledge_conflict=False)
        raise AssertionError("expected DraftOrderConflictError")
    except DraftOrderConflictError:
        pass

    assert len(session.query(Order).filter_by(project_id=project.id).all()) == 1


def test_replace_drafts_wins_when_both_flags_set(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Both flags True is not a contradiction the endpoint has to reject —
    replace_drafts is the more specific instruction, so the old draft is
    replaced, not kept alongside."""
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    old_order_id = create_orders_for_run(session, project.id, run.id)[0].id

    run2 = run_allocation(session, project.id)
    new_orders = create_orders_for_run(
        session, project.id, run2.id, replace_drafts=True, acknowledge_conflict=True
    )

    assert len(new_orders) == 1
    assert session.get(Order, old_order_id) is None
    assert len(session.query(Order).filter_by(project_id=project.id).all()) == 1


def test_fully_declined_draft_without_confirmed_prices_excluded_from_conflict(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """ADR-0026 п.2/п.3 of "Последствия": a draft Order whose only item is
    declined (and never confirmed) has nothing left to protect — it must not
    appear in suppliers_with_existing_drafts, and creating again for that
    supplier must proceed without a 409."""
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    first_orders = create_orders_for_run(session, project.id, run.id)
    item_id = first_orders[0].items[0].id
    client = _employee_client(make_user, make_session)
    client.patch(
        f"/orders/{first_orders[0].id}/items/{item_id}",
        json={"declined": True, "decline_reason": "no stock"},
        headers={"X-CSRF-Token": CSRF},
    )

    run2 = run_allocation(session, project.id)
    new_orders = create_orders_for_run(session, project.id, run2.id)

    assert len(new_orders) == 1
    assert new_orders[0].supplier_id == supplier.id
    all_drafts = (
        session.query(Order)
        .filter_by(project_id=project.id, supplier_id=supplier.id, status="draft")
        .all()
    )
    assert len(all_drafts) == 2  # the old, fully-declined draft is left alone, not deleted


def test_fully_declined_draft_with_confirmed_price_still_conflicts(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """ADR-0026 п.2: fully_declined does not override has_confirmed_prices —
    a declined item that was confirmed before being declined still guards
    the draft, same as any other has_confirmed_prices draft (ADR-0012 §1)."""
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    first_orders = create_orders_for_run(session, project.id, run.id)
    item_id = first_orders[0].items[0].id
    client = _employee_client(make_user, make_session)
    client.patch(
        f"/orders/{first_orders[0].id}/items/{item_id}",
        json={"confirmed_price": 5.00},
        headers={"X-CSRF-Token": CSRF},
    )
    client.patch(
        f"/orders/{first_orders[0].id}/items/{item_id}",
        json={"declined": True, "decline_reason": "cancelled after confirming"},
        headers={"X-CSRF-Token": CSRF},
    )

    run2 = run_allocation(session, project.id)
    response = client.post(
        f"/projects/{project.id}/allocations/{run2.id}/orders",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409
    suppliers = response.json()["suppliers_with_existing_drafts"]
    assert len(suppliers) == 1
    assert suppliers[0]["existing_draft_orders"][0]["has_confirmed_prices"] is True


def test_one_fully_declined_draft_filtered_other_supplier_draft_still_listed(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """ADR-0026 "Последствия": a supplier with two drafts, one fully declined
    (no confirmed prices) and one ordinary, must show only the ordinary one
    in suppliers_with_existing_drafts."""
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    first_orders = create_orders_for_run(session, project.id, run.id)
    item_id = first_orders[0].items[0].id
    client = _employee_client(make_user, make_session)
    client.patch(
        f"/orders/{first_orders[0].id}/items/{item_id}",
        json={"declined": True, "decline_reason": "no stock"},
        headers={"X-CSRF-Token": CSRF},
    )

    run2 = run_allocation(session, project.id)
    second_orders = create_orders_for_run(session, project.id, run2.id, acknowledge_conflict=True)
    ordinary_draft_id = second_orders[0].id

    run3 = run_allocation(session, project.id)
    response = client.post(
        f"/projects/{project.id}/allocations/{run3.id}/orders",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409
    suppliers = response.json()["suppliers_with_existing_drafts"]
    assert len(suppliers) == 1
    existing = suppliers[0]["existing_draft_orders"]
    assert len(existing) == 1
    assert existing[0]["order_id"] == str(ordinary_draft_id)


def test_supplier_whose_only_draft_is_fully_declined_absent_from_conflict_list(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """ADR-0026 "Последствия": when filtering leaves a supplier with zero
    remaining existing_draft_orders, that supplier must not appear in
    suppliers_with_existing_drafts at all — same as "no conflict"."""
    session, *_ = db_session
    supplier_a, material_a, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    supplier_b = make_supplier(name="B fully declined", flat_fee=0.0, free_shipping_threshold=0.0)
    material_b = make_material()
    make_price(material_b, supplier_b, price=6.00, availability=10)
    from app.models import ProjectItem

    session.add(ProjectItem(project_id=project.id, material_id=material_b.id, quantity=1))
    session.commit()

    run = run_allocation(session, project.id)
    first_orders = create_orders_for_run(session, project.id, run.id)
    client = _employee_client(make_user, make_session)
    b_order = next(o for o in first_orders if o.supplier_id == supplier_b.id)
    client.patch(
        f"/orders/{b_order.id}/items/{b_order.items[0].id}",
        json={"declined": True, "decline_reason": "no stock"},
        headers={"X-CSRF-Token": CSRF},
    )

    run2 = run_allocation(session, project.id)
    response = client.post(
        f"/projects/{project.id}/allocations/{run2.id}/orders",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409
    suppliers = response.json()["suppliers_with_existing_drafts"]
    supplier_ids = {s["supplier_id"] for s in suppliers}
    assert str(supplier_a.id) in supplier_ids
    assert str(supplier_b.id) not in supplier_ids


def test_acknowledge_conflict_keeps_per_supplier_granularity(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Per-supplier granularity (ADR-0012 п.3) is unchanged by the new flag:
    supplier A has a pre-existing draft, supplier B is new in this run —
    acknowledge_conflict creates for both and deletes nothing."""
    session, *_ = db_session
    supplier_a = make_supplier(name="A ack", flat_fee=0.0, free_shipping_threshold=0.0)
    supplier_b = make_supplier(name="B ack", flat_fee=0.0, free_shipping_threshold=0.0)
    material_a = make_material()
    material_b = make_material()
    make_price(material_a, supplier_a, price=5.00, availability=10)
    make_price(material_b, supplier_a, price=6.00, availability=10)
    make_price(material_b, supplier_b, price=6.00, availability=10)
    project = make_project([(material_a, 1), (material_b, 1)])

    run0 = run_allocation(session, project.id)
    first_orders = create_orders_for_run(session, project.id, run0.id)
    assert {o.supplier_id for o in first_orders} == {supplier_a.id}
    old_order_id = first_orders[0].id

    from app.allocation.service import override_allocation_line_supplier

    run1 = run_allocation(session, project.id)
    line_b = (
        session.query(AllocationLine)
        .filter_by(allocation_run_id=run1.id, material_id=material_b.id)
        .one()
    )
    override_allocation_line_supplier(session, run1.id, line_b.id, supplier_b.id)

    new_orders = create_orders_for_run(
        session, project.id, run1.id, acknowledge_conflict=True
    )

    assert {o.supplier_id for o in new_orders} == {supplier_a.id, supplier_b.id}
    assert session.get(Order, old_order_id) is not None  # A's old draft kept
    a_drafts = (
        session.query(Order)
        .filter_by(project_id=project.id, supplier_id=supplier_a.id, status="draft")
        .all()
    )
    assert len(a_drafts) == 2
