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
    set_order_item_fields,
)
from app.allocation.service import override_allocation_line_supplier, run_allocation
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
    email = f"employee-order{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session)


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
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
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
    client = _employee_client(make_user, make_session)

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


def test_create_orders_twice_with_replace_drafts_supersedes_first(
    db_session, make_supplier, make_material, make_price, make_project
):
    """ADR-0007 п.2 explicitly allows re-creating Orders for the same run
    (e.g. a partial reorder) — not deduplicated, not blocked outright.
    ADR-0012 gates this default (un-confirmed) path behind an explicit
    replace_drafts=True once a draft Order already exists for the supplier,
    rather than silently creating a duplicate — see
    tests/allocation/test_order_draft_conflict.py for the guard itself."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)

    first = create_orders_for_run(session, project.id, run.id)
    first_id = first[0].id
    second = create_orders_for_run(session, project.id, run.id, replace_drafts=True)

    assert len(first) == 1
    assert len(second) == 1
    assert first_id != second[0].id
    all_orders = session.query(Order).filter_by(project_id=project.id).all()
    assert len(all_orders) == 1  # replace_drafts=True supersedes the first draft


def test_create_orders_raises_for_unknown_run(db_session, make_project, make_material):
    session, *_ = db_session
    project = make_project([])

    try:
        create_orders_for_run(session, project.id, uuid.uuid4())
        raise AssertionError("expected RunNotFoundError")
    except RunNotFoundError:
        pass


def test_set_confirmed_price_sets_and_clears_confirmed_at(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}",
        json={"confirmed_price": 5.50},
        headers={"X-CSRF-Token": CSRF},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["confirmed_price"] == 5.50
    assert body["confirmed_at"] is not None

    cleared = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}",
        json={"confirmed_price": None},
        headers={"X-CSRF-Token": CSRF},
    )
    assert cleared.status_code == 200
    cleared_body = cleared.json()
    assert cleared_body["confirmed_price"] is None
    assert cleared_body["confirmed_at"] is None


def test_set_order_item_fields_sets_received_price_independent_of_confirmed(
    db_session, make_supplier, make_material, make_price, make_project
):
    """received_price can be set and read back without touching
    confirmed_price/confirmed_at at all — ADR-0013 п.1."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    item = set_order_item_fields(session, orders[0].id, item_id, received_price=4.75)

    assert float(item.received_price) == 4.75
    assert item.confirmed_price is None
    assert item.confirmed_at is None


def test_set_order_item_fields_confirmed_price_allowed_without_received_price(
    db_session, make_supplier, make_material, make_price, make_project
):
    """confirmed_price does not require received_price to be set first —
    ADR-0013 п.1 explicitly allows skipping the "received" step (e.g. phone
    confirmation at quoted_price)."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    item = set_order_item_fields(session, orders[0].id, item_id, confirmed_price=5.00)

    assert item.received_price is None
    assert float(item.confirmed_price) == 5.00
    assert item.confirmed_at is not None


def test_set_order_item_fields_declined_stamps_and_clears_declined_at(
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

    declined = set_order_item_fields(
        session, orders[0].id, item_id, declined=True, decline_reason="нет в наличии"
    )
    assert declined.declined_at is not None
    assert declined.decline_reason == "нет в наличии"

    undeclined = set_order_item_fields(session, orders[0].id, item_id, declined=False)
    assert undeclined.declined_at is None
    assert undeclined.decline_reason is None


def test_set_order_item_fields_declined_coexists_with_received_and_confirmed_price(
    db_session, make_supplier, make_material, make_price, make_project
):
    """ADR-0013 п.2: declined_at is not mutually exclusive with
    received_price/confirmed_price — "declined, but offered a substitute
    at another price" needs both facts on the same row."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    set_order_item_fields(session, orders[0].id, item_id, received_price=6.50)
    item = set_order_item_fields(
        session, orders[0].id, item_id, declined=True, decline_reason="снят с производства"
    )

    assert item.declined_at is not None
    assert float(item.received_price) == 6.50  # not cleared by declining


def test_set_order_item_fields_omitted_field_leaves_existing_value_untouched(
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

    set_order_item_fields(session, orders[0].id, item_id, received_price=4.75)
    # Second call only touches confirmed_price; received_price must survive.
    item = set_order_item_fields(session, orders[0].id, item_id, confirmed_price=5.00)

    assert float(item.received_price) == 4.75
    assert float(item.confirmed_price) == 5.00


def test_patch_order_item_sets_received_price_via_api(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}",
        json={"received_price": 4.90},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["received_price"] == 4.90
    assert body["confirmed_price"] is None


def test_patch_order_item_declines_via_api(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}",
        json={"declined": True, "decline_reason": "нет в наличии"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["declined_at"] is not None
    assert body["decline_reason"] == "нет в наличии"

    undeclined = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}",
        json={"declined": False},
        headers={"X-CSRF-Token": CSRF},
    )
    assert undeclined.status_code == 200
    undeclined_body = undeclined.json()
    assert undeclined_body["declined_at"] is None
    assert undeclined_body["decline_reason"] is None


def test_patch_order_item_partial_payload_leaves_other_fields_untouched_via_api(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id
    client = _employee_client(make_user, make_session)

    client.patch(
        f"/orders/{orders[0].id}/items/{item_id}",
        json={"received_price": 4.90},
        headers={"X-CSRF-Token": CSRF},
    )
    response = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}",
        json={"confirmed_price": 5.00},
        headers={"X-CSRF-Token": CSRF},
    )

    body = response.json()
    assert body["received_price"] == 4.90
    assert body["confirmed_price"] == 5.00


def test_price_delta_correct_and_null_when_unconfirmed():
    assert price_delta(10.00, None) == (None, None)

    delta, delta_pct = price_delta(10.00, 11.00)
    assert delta == 1.00
    assert round(delta_pct, 4) == 10.0

    delta_neg, delta_pct_neg = price_delta(20.00, 18.00)
    assert delta_neg == -2.00
    assert round(delta_pct_neg, 4) == -10.0


def test_order_item_out_includes_price_delta_via_api(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
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
    client = _employee_client(make_user, make_session)

    unconfirmed = client.get(f"/orders/{order_id}")
    unconfirmed_item = unconfirmed.json()["items"][0]
    assert unconfirmed_item["price_delta"] is None
    assert unconfirmed_item["price_delta_pct"] is None

    client.patch(
        f"/orders/{order_id}/items/{item_id}",
        json={"confirmed_price": 12.00},
        headers={"X-CSRF-Token": CSRF},
    )

    confirmed = client.get(f"/orders/{order_id}")
    confirmed_item = confirmed.json()["items"][0]
    assert confirmed_item["price_delta"] == 2.00
    assert round(confirmed_item["price_delta_pct"], 4) == 20.0


def test_order_out_expected_total_when_no_declines(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """ADR-0026 п.1/п.3: with nothing declined, expected_total must equal the
    total_amount snapshot and declined_amount must be 0."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=5.0, free_shipping_threshold=1000.0)
    material = make_material()
    make_price(material, supplier, price=10.00, availability=10)
    project = make_project([(material, 2)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    order_id = orders[0].id
    client = _employee_client(make_user, make_session)

    response = client.get(f"/orders/{order_id}")

    body = response.json()
    assert body["declined_amount"] == 0
    assert body["fully_declined"] is False
    assert body["expected_goods_total"] == body["total_amount"]
    assert body["expected_delivery_fee"] == body["delivery_fee"]
    assert body["expected_total"] == body["total_amount"] + body["delivery_fee"]


def test_order_out_expected_total_when_fully_declined(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """ADR-0026 п.1/п.2/п.4: all items declined -> expected_goods_total=0,
    expected_delivery_fee=0 (nothing left to ship), expected_total=0,
    fully_declined=True, declined_amount equals the full snapshot goods
    total."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=95.0, free_shipping_threshold=1000.0)
    material = make_material()
    make_price(material, supplier, price=14.826, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    order = orders[0]
    item_id = order.items[0].id
    client = _employee_client(make_user, make_session)

    client.patch(
        f"/orders/{order.id}/items/{item_id}",
        json={"declined": True, "decline_reason": "not available"},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.get(f"/orders/{order.id}")
    body = response.json()

    assert body["fully_declined"] is True
    assert body["declined_amount"] == body["total_amount"]
    assert body["expected_goods_total"] == 0
    assert body["expected_delivery_fee"] == 0
    assert body["expected_total"] == 0


def test_order_out_expected_total_when_partially_declined(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """ADR-0026 п.3/п.4: only some items declined -> expected_delivery_fee
    stays the snapshot delivery_fee (not recomputed against the supplier's
    free-shipping threshold), expected_goods_total sums only the
    non-declined items, and fully_declined is False."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=50.0, free_shipping_threshold=1000.0)
    material_a = make_material()
    material_b = make_material()
    make_price(material_a, supplier, price=120.00, availability=10)
    make_price(material_b, supplier, price=380.00, availability=10)
    project = make_project([(material_a, 1), (material_b, 1)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    order = orders[0]
    declined_item = next(i for i in order.items if float(i.quoted_price) == 120.00)
    client = _employee_client(make_user, make_session)

    client.patch(
        f"/orders/{order.id}/items/{declined_item.id}",
        json={"declined": True},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.get(f"/orders/{order.id}")
    body = response.json()

    assert body["fully_declined"] is False
    assert body["declined_amount"] == 120.00
    assert body["expected_goods_total"] == 380.00
    assert body["expected_delivery_fee"] == body["delivery_fee"] == 50.00
    assert body["expected_total"] == 430.00


def test_order_out_empty_order_is_not_fully_declined(
    db_session, make_project, make_user, make_session, make_supplier
):
    """ADR-0026 п.2: an Order with no items at all is not "fully declined" —
    there is no actual decline fact to report."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    project = make_project([])
    empty_order = Order(
        project_id=project.id, supplier_id=supplier.id, status="draft",
        total_amount=0, delivery_fee=0,
    )
    session.add(empty_order)
    session.commit()
    client = _employee_client(make_user, make_session)

    response = client.get(f"/orders/{empty_order.id}")

    body = response.json()
    assert body["fully_declined"] is False
    assert body["expected_total"] == 0
    assert body["declined_amount"] == 0


def test_post_orders_returns_404_for_unknown_run(
    db_session, make_project, make_user, make_session
):
    session, *_ = db_session
    project = make_project([])
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/allocations/{uuid.uuid4()}/orders",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_post_orders_returns_404_when_run_belongs_to_different_project(
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

    response = client.post(
        f"/projects/{project_b.id}/allocations/{run_id}/orders",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_get_order_returns_404_for_unknown_order(make_user, make_session):
    client = _employee_client(make_user, make_session)
    response = client.get(f"/orders/{uuid.uuid4()}")

    assert response.status_code == 404


def test_patch_order_item_returns_404_for_unknown_order(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/orders/{uuid.uuid4()}/items/{item_id}",
        json={"confirmed_price": 5.0},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_patch_order_item_returns_404_for_item_from_different_order(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
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
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/orders/{orders_a[0].id}/items/{item_from_b}",
        json={"confirmed_price": 5.0},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_list_project_orders_returns_all_orders_for_project(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier_a = make_supplier(name="A", flat_fee=0.0, free_shipping_threshold=0.0)
    supplier_b = make_supplier(name="B", flat_fee=0.0, free_shipping_threshold=0.0)
    material_a = make_material()
    material_b = make_material()
    make_price(material_a, supplier_a, price=5.00, availability=10)
    make_price(material_b, supplier_b, price=6.00, availability=10)
    project = make_project([(material_a, 10), (material_b, 10)])

    run = run_allocation(session, project.id)
    create_orders_for_run(session, project.id, run.id)
    client = _employee_client(make_user, make_session)

    response = client.get(f"/projects/{project.id}/orders")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_project_orders_returns_404_for_unknown_project(make_user, make_session):
    client = _employee_client(make_user, make_session)
    response = client.get(f"/projects/{uuid.uuid4()}/orders")

    assert response.status_code == 404


def test_patch_target_price_does_not_touch_other_fields(
    db_session, make_supplier, make_material, make_price, make_project
):
    """ADR-0027: target_price PATCH follows the same independent _UNSET
    pattern as confirmed_price/received_price — setting it must not touch
    received_price/confirmed_price/declined_at."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    set_order_item_fields(session, orders[0].id, item_id, received_price=4.75)
    set_order_item_fields(
        session, orders[0].id, item_id, declined=True, decline_reason="торгуемся"
    )
    item = set_order_item_fields(session, orders[0].id, item_id, target_price=4.60)

    assert float(item.target_price) == 4.60
    assert float(item.received_price) == 4.75
    assert item.confirmed_price is None
    assert item.declined_at is not None
    assert item.decline_reason == "торгуемся"


def test_patch_target_price_null_clears_field(
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

    set_order_item_fields(session, orders[0].id, item_id, target_price=4.60)
    item = set_order_item_fields(session, orders[0].id, item_id, target_price=None)

    assert item.target_price is None


def test_patch_target_price_via_api_leaves_other_fields_untouched(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id
    client = _employee_client(make_user, make_session)

    client.patch(
        f"/orders/{orders[0].id}/items/{item_id}",
        json={"received_price": 4.90},
        headers={"X-CSRF-Token": CSRF},
    )
    response = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}",
        json={"target_price": 4.60},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["target_price"] == 4.60
    assert body["received_price"] == 4.90
    assert body["confirmed_price"] is None


def test_received_price_delta_null_when_no_received_price():
    delta, delta_pct = price_delta(10.00, None)
    assert delta is None
    assert delta_pct is None


def test_order_item_out_includes_received_price_delta_via_api(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """ADR-0027 §3: received_price_delta/received_price_delta_pct compare
    received_price against quoted_price, independently of price_delta
    (which compares confirmed_price against quoted_price)."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=10.00, availability=10)
    project = make_project([(material, 1)])

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    order_id = orders[0].id
    item_id = orders[0].items[0].id
    client = _employee_client(make_user, make_session)

    unset = client.get(f"/orders/{order_id}")
    unset_item = unset.json()["items"][0]
    assert unset_item["received_price_delta"] is None
    assert unset_item["received_price_delta_pct"] is None

    client.patch(
        f"/orders/{order_id}/items/{item_id}",
        json={"received_price": 11.00},
        headers={"X-CSRF-Token": CSRF},
    )

    received = client.get(f"/orders/{order_id}")
    received_item = received.json()["items"][0]
    assert received_item["received_price_delta"] == 1.00
    assert round(received_item["received_price_delta_pct"], 4) == 10.0


def test_received_price_delta_independent_of_price_delta_both_set(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    """A row can have a discrepancy on both axes at once — negotiated down
    from received_price but still not back to quoted_price (ADR-0027 §3)."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=10.00, availability=10)
    project = make_project([(material, 1)])

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    order_id = orders[0].id
    item_id = orders[0].items[0].id
    client = _employee_client(make_user, make_session)

    client.patch(
        f"/orders/{order_id}/items/{item_id}",
        json={"received_price": 13.00},
        headers={"X-CSRF-Token": CSRF},
    )
    client.patch(
        f"/orders/{order_id}/items/{item_id}",
        json={"confirmed_price": 12.00},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.get(f"/orders/{order_id}")
    item = response.json()["items"][0]

    assert item["received_price_delta"] == 3.00
    assert round(item["received_price_delta_pct"], 4) == 30.0
    assert item["price_delta"] == 2.00
    assert round(item["price_delta_pct"], 4) == 20.0


def test_order_item_out_includes_target_price_via_api(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
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
    client = _employee_client(make_user, make_session)

    client.patch(
        f"/orders/{order_id}/items/{item_id}",
        json={"target_price": 8.50},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.get(f"/orders/{order_id}")
    item = response.json()["items"][0]
    assert item["target_price"] == 8.50
