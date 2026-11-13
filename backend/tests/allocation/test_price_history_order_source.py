"""GET /prices/history для версии цены, созданной из ордера (ADR-0030 →
ADR-0054 §6). Отдельный файл в tests/allocation: только здесь есть фикстуры
проекта и ордера. В проде на таких парах история падала с 500."""

import uuid

from fastapi.testclient import TestClient

from app.allocation.order_service import create_orders_for_run
from app.allocation.service import run_allocation
from app.api.price import version_price
from app.main import app

CSRF = "test-csrf-token"


def _admin_client(make_user, make_session):
    admin = make_user(
        email=f"admin-history-{uuid.uuid4().hex[:8]}@screen-factory-florida.com", role="admin"
    )
    client = TestClient(app)
    client.cookies.set("session_id", str(make_session(admin, csrf_token=CSRF).id))
    return client, admin


def test_history_shows_order_sourced_version_with_order_and_author(
    db_session, make_supplier, make_material, make_price, make_project, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    order = create_orders_for_run(session, project.id, run.id)[0]
    item = order.items[0]
    client, admin = _admin_client(make_user, make_session)
    version_price(
        session,
        material_id=material.id,
        supplier_id=supplier.id,
        price=4.50,
        created_by_user_id=admin.id,
        source_order_item_id=item.id,
    )

    response = client.get(
        "/prices/history",
        params={"material_id": str(material.id), "supplier_id": str(supplier.id)},
    )

    assert response.status_code == 200, response.text
    newest, oldest = response.json()
    assert newest["source"] == "order"
    assert newest["order_id"] == str(order.id)
    assert newest["order_title"] == project.title
    assert newest["created_by_name"] == admin.name
    assert newest["change"] == "down"
    assert oldest["source"] == "manual"
