"""Tests for the draft-Order recreation guard — ADR-0012.

Covers: conflict detection on Order creation when draft Orders already exist
for a supplier in the current run's supplier_summaries, the 409 response body
shape (list of existing_draft_orders per supplier, has_confirmed_prices per
entry), replace_drafts=True semantics (delete old draft Order/OrderItem then
recreate), per-supplier granularity, and approved/sent Orders never being
treated as conflicts.
"""

from fastapi.testclient import TestClient

from app.allocation.order_service import (
    DraftOrderConflictError,
    create_orders_for_run,
)
from app.allocation.service import run_allocation
from app.main import app
from app.models import AllocationLine, Order, OrderItem

client = TestClient(app)


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
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    client.post(f"/projects/{project.id}/allocations/{run.id}/orders")

    run2 = run_allocation(session, project.id)
    response = client.post(f"/projects/{project.id}/allocations/{run2.id}/orders")

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
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier, material, project = _setup_single_supplier_project(
        make_supplier, make_material, make_price, make_project
    )
    run = run_allocation(session, project.id)
    first_orders = create_orders_for_run(session, project.id, run.id)
    item_id = first_orders[0].items[0].id
    client.patch(
        f"/orders/{first_orders[0].id}/items/{item_id}", json={"confirmed_price": 5.50}
    )

    run2 = run_allocation(session, project.id)
    response = client.post(f"/projects/{project.id}/allocations/{run2.id}/orders")

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
