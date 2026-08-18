"""Tests for Order/OrderItem creation and confirmed-price entry — ADR-0007.

Covers: snapshotting the current (possibly overridden) AllocationLine state
into OrderItem.quoted_price, ordered_at marking, confirmed_price/confirmed_at
PATCH semantics, price_delta/price_delta_pct computation, repeated Order
creation for the same run, and 404s.
"""

import uuid

from fastapi.testclient import TestClient

from app.allocation.order_service import (
    RunNotFoundError,
    create_orders_for_run,
    price_delta,
)
from app.allocation.service import override_allocation_line_supplier, run_allocation
from app.main import app
from app.models import AllocationLine, Order

client = TestClient(app)


def test_create_orders_snapshots_overridden_price_not_original_ilp_price(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    cheap_supplier = make_supplier(
        name="Cheap Supplier", flat_fee=0.0, free_shipping_threshold=0.0
    )
    override_supplier = make_supplier(
        name="Override Supplier", flat_fee=0.0, free_shipping_threshold=0.0
    )
    material = make_material()
    make_price(material, cheap_supplier, price=5.00, availability=10)
    make_price(material, override_supplier, price=9.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()
    assert line.supplier_id == cheap_supplier.id  # sanity: ILP picked the cheap one

    override_allocation_line_supplier(session, run.id, line.id, override_supplier.id)

    orders = create_orders_for_run(session, project.id, run.id)

    assert len(orders) == 1
    order = orders[0]
    assert order.supplier_id == override_supplier.id
    assert len(order.items) == 1
    item = order.items[0]
    assert float(item.quoted_price) == 9.00  # overridden price, not the original 5.00
    assert item.quantity == 10


def test_create_orders_marks_lines_ordered_at(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()
    assert line.ordered_at is None

    create_orders_for_run(session, project.id, run.id)
    session.refresh(line)

    assert line.ordered_at is not None


def test_get_allocation_run_exposes_ordered_at_on_line(
    db_session, make_supplier, make_material, make_price, make_project
):
    """AllocationLineOut must surface ordered_at — the frontend needs it
    (alongside overridden_at) to detect "overridden after the Order was
    already created". See ADR-0007 п.2."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)
    create_orders_for_run(session, project.id, run.id)

    response = client.get(f"/projects/{project.id}/allocations/{run.id}")

    line = response.json()["lines"][0]
    assert line["ordered_at"] is not None


def test_create_orders_one_per_supplier(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier_a = make_supplier(name="A", flat_fee=0.0, free_shipping_threshold=0.0)
    supplier_b = make_supplier(name="B", flat_fee=0.0, free_shipping_threshold=1000.0)
    material_a = make_material()
    material_b = make_material()
    make_price(material_a, supplier_a, price=5.00, availability=10)
    make_price(material_b, supplier_b, price=6.00, availability=10)
    project = make_project([(material_a, 1), (material_b, 1)])

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)

    assert len(orders) == 2
    suppliers = {order.supplier_id for order in orders}
    assert suppliers == {supplier_a.id, supplier_b.id}


def test_create_orders_twice_for_same_run_does_not_conflict(
    db_session, make_supplier, make_material, make_price, make_project
):
    """ADR-0007 п.2 explicitly allows re-creating Orders for the same run
    (e.g. a partial reorder) — not deduplicated, not blocked."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)

    first = create_orders_for_run(session, project.id, run.id)
    second = create_orders_for_run(session, project.id, run.id)

    assert len(first) == 1
    assert len(second) == 1
    assert first[0].id != second[0].id
    all_orders = session.query(Order).filter_by(project_id=project.id).all()
    assert len(all_orders) == 2


def test_create_orders_raises_for_unknown_run(db_session, make_project, make_material):
    session, *_ = db_session
    project = make_project([])

    try:
        create_orders_for_run(session, project.id, uuid.uuid4())
        raise AssertionError("expected RunNotFoundError")
    except RunNotFoundError:
        pass


def test_set_confirmed_price_sets_and_clears_confirmed_at(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    response = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}", json={"confirmed_price": 5.50}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["confirmed_price"] == 5.50
    assert body["confirmed_at"] is not None

    cleared = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}", json={"confirmed_price": None}
    )
    assert cleared.status_code == 200
    cleared_body = cleared.json()
    assert cleared_body["confirmed_price"] is None
    assert cleared_body["confirmed_at"] is None


def test_price_delta_correct_and_null_when_unconfirmed():
    assert price_delta(10.00, None) == (None, None)

    delta, delta_pct = price_delta(10.00, 11.00)
    assert delta == 1.00
    assert round(delta_pct, 4) == 10.0

    delta_neg, delta_pct_neg = price_delta(20.00, 18.00)
    assert delta_neg == -2.00
    assert round(delta_pct_neg, 4) == -10.0


def test_order_item_out_includes_price_delta_via_api(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=10.00, availability=10)
    project = make_project([(material, 1)])

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    order_id = orders[0].id
    item_id = orders[0].items[0].id

    unconfirmed = client.get(f"/orders/{order_id}")
    unconfirmed_item = unconfirmed.json()["items"][0]
    assert unconfirmed_item["price_delta"] is None
    assert unconfirmed_item["price_delta_pct"] is None

    client.patch(f"/orders/{order_id}/items/{item_id}", json={"confirmed_price": 12.00})

    confirmed = client.get(f"/orders/{order_id}")
    confirmed_item = confirmed.json()["items"][0]
    assert confirmed_item["price_delta"] == 2.00
    assert round(confirmed_item["price_delta_pct"], 4) == 20.0


def test_post_orders_returns_404_for_unknown_run(db_session, make_project):
    session, *_ = db_session
    project = make_project([])

    response = client.post(f"/projects/{project.id}/allocations/{uuid.uuid4()}/orders")

    assert response.status_code == 404


def test_post_orders_returns_404_when_run_belongs_to_different_project(
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

    response = client.post(f"/projects/{project_b.id}/allocations/{run_id}/orders")

    assert response.status_code == 404


def test_get_order_returns_404_for_unknown_order():
    response = client.get(f"/orders/{uuid.uuid4()}")

    assert response.status_code == 404


def test_patch_order_item_returns_404_for_unknown_order(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    response = client.patch(
        f"/orders/{uuid.uuid4()}/items/{item_id}", json={"confirmed_price": 5.0}
    )

    assert response.status_code == 404


def test_patch_order_item_returns_404_for_item_from_different_order(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material_a = make_material()
    material_b = make_material()
    make_price(material_a, supplier, price=5.00, availability=10)
    make_price(material_b, supplier, price=6.00, availability=1000.0)
    project_a = make_project([(material_a, 1)])
    project_b = make_project([(material_b, 1)])

    run_a = run_allocation(session, project_a.id)
    run_b = run_allocation(session, project_b.id)
    orders_a = create_orders_for_run(session, project_a.id, run_a.id)
    orders_b = create_orders_for_run(session, project_b.id, run_b.id)
    item_from_b = orders_b[0].items[0].id

    response = client.patch(
        f"/orders/{orders_a[0].id}/items/{item_from_b}", json={"confirmed_price": 5.0}
    )

    assert response.status_code == 404


def test_list_project_orders_returns_all_orders_for_project(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)
    create_orders_for_run(session, project.id, run.id)
    create_orders_for_run(session, project.id, run.id)

    response = client.get(f"/projects/{project.id}/orders")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_project_orders_returns_404_for_unknown_project():
    response = client.get(f"/projects/{uuid.uuid4()}/orders")

    assert response.status_code == 404
