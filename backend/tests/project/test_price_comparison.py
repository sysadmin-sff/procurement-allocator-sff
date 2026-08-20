"""Tests for GET /projects/{project_id}/price-comparison — ADR-0016 backend.

Covers both sections of the response: `plan` (from active Price rows,
independent of any Order) and `supplier_responses` (from OrderItem rows on
this project's Orders, only for suppliers who were actually sent something).
"""

import datetime
import uuid

from fastapi.testclient import TestClient

from app.allocation.order_service import set_order_item_fields
from app.main import app
from app.models import Order, OrderItem

client = TestClient(app)


def _row_for(body, project_item_id):
    return next(r for r in body["rows"] if r["project_item_id"] == str(project_item_id))


# --- plan section ---


def test_plan_marks_lowest_price_as_cheapest_regardless_of_availability(
    db_session, make_project, make_material, make_supplier, make_price
):
    session, *_ = db_session
    material = make_material()
    project = make_project([(material, 5)])
    item = project.items[0]

    cheap_but_short = make_supplier(name="Cheap Short")
    make_price(material, cheap_but_short, price=4.00, availability=1)  # qty is 5
    expensive_plenty = make_supplier(name="Expensive Plenty")
    make_price(material, expensive_plenty, price=9.00, availability=100)

    response = client.get(f"/projects/{project.id}/price-comparison")

    assert response.status_code == 200
    row = _row_for(response.json(), item.id)
    plan_by_supplier = {c["supplier_id"]: c for c in row["plan"]}
    assert plan_by_supplier[str(cheap_but_short.id)]["is_cheapest"] is True
    assert plan_by_supplier[str(expensive_plenty.id)]["is_cheapest"] is False


def test_plan_is_empty_list_for_material_with_no_active_price(
    db_session, make_project, make_material
):
    material = make_material()
    project = make_project([(material, 5)])
    item = project.items[0]

    response = client.get(f"/projects/{project.id}/price-comparison")

    assert response.status_code == 200
    row = _row_for(response.json(), item.id)
    assert row["plan"] == []
    assert row["supplier_responses"] == []


# --- supplier_responses section ---


def test_supplier_without_order_does_not_appear_in_supplier_responses(
    db_session, make_project, make_material, make_supplier, make_price
):
    material = make_material()
    project = make_project([(material, 5)])
    item = project.items[0]
    make_supplier(name="Never Ordered")
    # No Order at all for this project.

    response = client.get(f"/projects/{project.id}/price-comparison")

    assert response.status_code == 200
    row = _row_for(response.json(), item.id)
    assert row["supplier_responses"] == []


def test_project_without_any_order_leaves_supplier_responses_empty_but_plan_filled(
    db_session, make_project, make_material, make_supplier, make_price
):
    material = make_material()
    project = make_project([(material, 5)])
    item = project.items[0]
    supplier = make_supplier(name="Has Price")
    make_price(material, supplier, price=5.00, availability=10)

    response = client.get(f"/projects/{project.id}/price-comparison")

    assert response.status_code == 200
    row = _row_for(response.json(), item.id)
    assert len(row["plan"]) == 1
    assert row["supplier_responses"] == []


def test_declined_response_is_never_cheapest_even_with_lowest_received_price(
    db_session, make_project, make_material, make_supplier
):
    session, *_ = db_session
    material = make_material()
    project = make_project([(material, 5)])
    item = project.items[0]

    declining_supplier = make_supplier(name="Declining")
    order_declining = Order(
        project_id=project.id, supplier_id=declining_supplier.id, status="draft"
    )
    session.add(order_declining)
    session.flush()
    declined_item = OrderItem(
        order_id=order_declining.id,
        material_id=material.id,
        quantity=5,
        quoted_price=3.00,
    )
    session.add(declined_item)
    session.flush()
    set_order_item_fields(
        session, order_declining.id, declined_item.id, received_price=1.00, declined=True
    )

    healthy_supplier = make_supplier(name="Healthy")
    order_healthy = Order(project_id=project.id, supplier_id=healthy_supplier.id, status="draft")
    session.add(order_healthy)
    session.flush()
    healthy_item = OrderItem(
        order_id=order_healthy.id,
        material_id=material.id,
        quantity=5,
        quoted_price=9.00,
    )
    session.add(healthy_item)
    session.commit()

    response = client.get(f"/projects/{project.id}/price-comparison")

    row = _row_for(response.json(), item.id)
    responses_by_supplier = {r["supplier_id"]: r for r in row["supplier_responses"]}
    assert responses_by_supplier[str(declining_supplier.id)]["is_cheapest"] is False
    assert responses_by_supplier[str(declining_supplier.id)]["declined_at"] is not None
    assert responses_by_supplier[str(healthy_supplier.id)]["is_cheapest"] is True


def test_multiple_orders_same_supplier_uses_row_from_order_containing_material_with_max_created_at(
    db_session, make_project, make_material, make_supplier
):
    """Order A (older, contains material), Order B (newer, does NOT contain
    material), Order C (newest, contains material) -> must use C, not B (no
    material row there) or A (older) — ADR-0016 §3."""
    session, *_ = db_session
    material = make_material()
    other_material = make_material()
    project = make_project([(material, 5)])
    item = project.items[0]
    supplier = make_supplier(name="Repeat Orderer")

    base_time = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

    order_a = Order(project_id=project.id, supplier_id=supplier.id, status="draft")
    session.add(order_a)
    session.flush()
    session.add(
        OrderItem(order_id=order_a.id, material_id=material.id, quantity=5, quoted_price=5.00)
    )
    session.flush()
    session.execute(
        Order.__table__.update().where(Order.id == order_a.id).values(created_at=base_time)
    )

    order_b = Order(project_id=project.id, supplier_id=supplier.id, status="draft")
    session.add(order_b)
    session.flush()
    session.add(
        OrderItem(
            order_id=order_b.id, material_id=other_material.id, quantity=1, quoted_price=1.00
        )
    )
    session.flush()
    session.execute(
        Order.__table__.update()
        .where(Order.id == order_b.id)
        .values(created_at=base_time + datetime.timedelta(days=1))
    )

    order_c = Order(project_id=project.id, supplier_id=supplier.id, status="draft")
    session.add(order_c)
    session.flush()
    session.add(
        OrderItem(order_id=order_c.id, material_id=material.id, quantity=5, quoted_price=7.00)
    )
    session.flush()
    session.execute(
        Order.__table__.update()
        .where(Order.id == order_c.id)
        .values(created_at=base_time + datetime.timedelta(days=2))
    )
    session.commit()

    response = client.get(f"/projects/{project.id}/price-comparison")

    row = _row_for(response.json(), item.id)
    assert len(row["supplier_responses"]) == 1
    assert row["supplier_responses"][0]["quoted_price"] == 7.00


def test_is_cheapest_prefers_confirmed_then_received_then_quoted_across_suppliers(
    db_session, make_project, make_material, make_supplier
):
    session, *_ = db_session
    material = make_material()
    project = make_project([(material, 5)])
    item = project.items[0]

    # Supplier A: only quoted=10 -> effective 10
    supplier_a = make_supplier(name="A")
    order_a = Order(project_id=project.id, supplier_id=supplier_a.id, status="draft")
    session.add(order_a)
    session.flush()
    session.add(
        OrderItem(order_id=order_a.id, material_id=material.id, quantity=5, quoted_price=10.00)
    )

    # Supplier B: quoted=10, received=6 -> effective 6 (received wins over quoted)
    supplier_b = make_supplier(name="B")
    order_b = Order(project_id=project.id, supplier_id=supplier_b.id, status="draft")
    session.add(order_b)
    session.flush()
    item_b = OrderItem(
        order_id=order_b.id, material_id=material.id, quantity=5, quoted_price=10.00
    )
    session.add(item_b)
    session.flush()

    # Supplier C: quoted=10, received=6, confirmed=8 -> effective 8 (confirmed wins over received)
    supplier_c = make_supplier(name="C")
    order_c = Order(project_id=project.id, supplier_id=supplier_c.id, status="draft")
    session.add(order_c)
    session.flush()
    item_c = OrderItem(
        order_id=order_c.id, material_id=material.id, quantity=5, quoted_price=10.00
    )
    session.add(item_c)
    session.flush()

    session.commit()
    set_order_item_fields(session, order_b.id, item_b.id, received_price=6.00)
    set_order_item_fields(session, order_c.id, item_c.id, received_price=6.00, confirmed_price=8.00)

    response = client.get(f"/projects/{project.id}/price-comparison")

    row = _row_for(response.json(), item.id)
    responses_by_supplier = {r["supplier_id"]: r for r in row["supplier_responses"]}
    # B's effective price (6, received) is lowest overall -> B is cheapest,
    # not C (effective 8, confirmed) despite C having a "more final" field.
    assert responses_by_supplier[str(supplier_b.id)]["is_cheapest"] is True
    assert responses_by_supplier[str(supplier_a.id)]["is_cheapest"] is False
    assert responses_by_supplier[str(supplier_c.id)]["is_cheapest"] is False


def test_returns_404_for_missing_project():
    response = client.get(f"/projects/{uuid.uuid4()}/price-comparison")

    assert response.status_code == 404
