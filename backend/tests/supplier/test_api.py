import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.models import Price

CSRF = "test-csrf-token"


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


_admin_email_counter = [0]


def _admin_client(make_user, make_session):
    _admin_email_counter[0] += 1
    email = f"admin-supplier{_admin_email_counter[0]}@screen-factory-florida.com"
    admin = make_user(email=email, role="admin")
    admin_session = make_session(admin, csrf_token=CSRF)
    return _client_as(admin_session)


def test_create_supplier_returns_201_with_body(db_session, make_user, make_session):
    session, supplier_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/suppliers",
        json={
            "name": "Acme Fencing",
            "contacts": "sales@acme.example",
            "currency": "USD",
            "delivery_policy": {
                "flat_fee": 25.0,
                "free_shipping_threshold": 500.0,
                "per_order_min_amount": 100.0,
                "lead_time_days": 3,
            },
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    supplier_ids.append(uuid.UUID(body["id"]))
    assert body["name"] == "Acme Fencing"
    assert body["contacts"] == "sales@acme.example"
    assert body["delivery_policy"]["flat_fee"] == 25.0
    assert body["delivery_policy"]["lead_time_days"] == 3


def test_create_supplier_defaults_delivery_policy(db_session, make_user, make_session):
    session, supplier_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/suppliers", json={"name": "Minimal Supplier"}, headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 201
    body = response.json()
    supplier_ids.append(uuid.UUID(body["id"]))
    assert body["delivery_policy"] == {
        "flat_fee": 0.0,
        "free_shipping_threshold": None,
        "per_order_min_amount": 0.0,
        "lead_time_days": 0,
    }


def test_get_supplier_returns_created_supplier(db_session, make_supplier, make_user, make_session):
    supplier = make_supplier(name="Get Me")
    client = _admin_client(make_user, make_session)

    response = client.get(f"/suppliers/{supplier.id}")

    assert response.status_code == 200
    assert response.json()["name"] == "Get Me"


def test_get_supplier_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.get(f"/suppliers/{uuid.uuid4()}")

    assert response.status_code == 404


def test_list_suppliers_includes_created_suppliers(
    db_session, make_supplier, make_user, make_session
):
    supplier = make_supplier(name="Listed Supplier")
    client = _admin_client(make_user, make_session)

    response = client.get("/suppliers")

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert str(supplier.id) in ids


def test_update_supplier_changes_fields(db_session, make_supplier, make_user, make_session):
    supplier = make_supplier(name="Old Name", flat_fee=10.0)
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/suppliers/{supplier.id}",
        json={
            "name": "New Name",
            "currency": "USD",
            "delivery_policy": {
                "flat_fee": 50.0,
                "free_shipping_threshold": 0.0,
                "per_order_min_amount": 0.0,
                "lead_time_days": 0,
            },
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New Name"
    assert body["delivery_policy"]["flat_fee"] == 50.0


def test_update_supplier_partial_payload_preserves_omitted_fields(
    db_session, make_supplier, make_user, make_session
):
    supplier = make_supplier(
        name="Kept Name",
        contacts="ops@example.com",
        currency="EUR",
        flat_fee=15.0,
        free_shipping_threshold=200.0,
        per_order_min_amount=50.0,
        lead_time_days=5,
    )
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/suppliers/{supplier.id}",
        json={"name": "Renamed Only"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed Only"
    assert body["contacts"] == "ops@example.com"
    assert body["currency"] == "EUR"
    assert body["delivery_policy"] == {
        "flat_fee": 15.0,
        "free_shipping_threshold": 200.0,
        "per_order_min_amount": 50.0,
        "lead_time_days": 5,
    }


def test_update_supplier_partial_delivery_policy_merges_not_replaces(
    db_session, make_supplier, make_user, make_session
):
    supplier = make_supplier(
        flat_fee=15.0,
        free_shipping_threshold=200.0,
        per_order_min_amount=50.0,
        lead_time_days=5,
    )
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/suppliers/{supplier.id}",
        json={"delivery_policy": {"flat_fee": 99.0}},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["delivery_policy"] == {
        "flat_fee": 99.0,
        "free_shipping_threshold": 200.0,
        "per_order_min_amount": 50.0,
        "lead_time_days": 5,
    }


def test_update_supplier_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/suppliers/{uuid.uuid4()}",
        json={"name": "Doesn't matter"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_delete_supplier_removes_it(db_session, make_supplier, make_user, make_session):
    session, supplier_ids, _user_ids = db_session
    supplier = make_supplier(name="Deletable")
    supplier_ids.remove(supplier.id)
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/suppliers/{supplier.id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 204
    assert client.get(f"/suppliers/{supplier.id}").status_code == 404


def test_delete_supplier_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/suppliers/{uuid.uuid4()}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 404


def test_delete_supplier_returns_409_when_referenced_by_price(
    db_session, make_supplier, make_user, make_session
):
    session, supplier_ids, _user_ids = db_session
    import datetime

    from app.models import Material

    supplier = make_supplier(name="Referenced Supplier")
    material = Material(
        internal_sku=f"SKU-{uuid.uuid4().hex[:12]}",
        canonical_name="Test Material",
        unit="ft",
        attributes={},
    )
    session.add(material)
    session.flush()
    price = Price(
        material=material,
        supplier=supplier,
        price=10.0,
        currency="USD",
        valid_from=datetime.date.today(),
        valid_to=None,
    )
    session.add(price)
    session.commit()
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/suppliers/{supplier.id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 409

    session.delete(price)
    session.delete(material)
    session.commit()


def test_list_suppliers_no_session_returns_401():
    client = TestClient(app)
    response = client.get("/suppliers")
    assert response.status_code == 401


def test_list_suppliers_as_employee_returns_403(make_user, make_session):
    employee = make_user(role="employee")
    employee_session = make_session(employee)
    response = _client_as(employee_session).get("/suppliers")
    assert response.status_code == 403


def test_list_suppliers_as_admin_succeeds(make_user, make_session):
    admin = make_user(email="admin-supplier-list@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin)
    response = _client_as(admin_session).get("/suppliers")
    assert response.status_code == 200
