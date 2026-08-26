import datetime
import uuid

from fastapi.testclient import TestClient

from app.main import app

CSRF = "test-csrf-token"


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


_admin_email_counter = [0]


def _admin_client(make_user, make_session):
    _admin_email_counter[0] += 1
    email = f"admin-price{_admin_email_counter[0]}@screen-factory-florida.com"
    admin = make_user(email=email, role="admin")
    admin_session = make_session(admin, csrf_token=CSRF)
    return _client_as(admin_session)


def test_create_price_returns_201_with_body(
    db_session, make_material, make_supplier, make_user, make_session
):
    material = make_material()
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/prices",
        json={
            "material_id": str(material.id),
            "supplier_id": str(supplier.id),
            "price": 12.50,
            "currency": "USD",
            "availability": 100,
            "min_order_qty": 5,
            "valid_from": str(datetime.date.today()),
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["price"] == 12.50
    assert body["valid_to"] is None
    assert body["material_id"] == str(material.id)
    assert body["supplier_id"] == str(supplier.id)


def test_create_price_returns_404_for_unknown_material(
    db_session, make_supplier, make_user, make_session
):
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/prices",
        json={
            "material_id": str(uuid.uuid4()),
            "supplier_id": str(supplier.id),
            "price": 10.0,
            "valid_from": str(datetime.date.today()),
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_create_price_returns_404_for_unknown_supplier(
    db_session, make_material, make_user, make_session
):
    material = make_material()
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/prices",
        json={
            "material_id": str(material.id),
            "supplier_id": str(uuid.uuid4()),
            "price": 10.0,
            "valid_from": str(datetime.date.today()),
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_create_price_returns_422_when_valid_to_before_valid_from(
    db_session, make_material, make_supplier, make_user, make_session
):
    material = make_material()
    supplier = make_supplier()
    today = datetime.date.today()
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/prices",
        json={
            "material_id": str(material.id),
            "supplier_id": str(supplier.id),
            "price": 10.0,
            "valid_from": str(today),
            "valid_to": str(today - datetime.timedelta(days=1)),
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_create_price_returns_409_when_active_price_already_exists(
    db_session, make_material, make_supplier, make_price, make_user, make_session
):
    material = make_material()
    supplier = make_supplier()
    make_price(material, supplier, price=8.0)
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/prices",
        json={
            "material_id": str(material.id),
            "supplier_id": str(supplier.id),
            "price": 9.0,
            "valid_from": str(datetime.date.today()),
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409


def test_create_price_allows_second_price_when_first_is_closed(
    db_session, make_material, make_supplier, make_price, make_user, make_session
):
    material = make_material()
    supplier = make_supplier()
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    make_price(material, supplier, price=8.0, valid_from=yesterday, valid_to=yesterday)
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/prices",
        json={
            "material_id": str(material.id),
            "supplier_id": str(supplier.id),
            "price": 9.0,
            "valid_from": str(datetime.date.today()),
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201


def test_get_price_returns_created_price(
    db_session, make_material, make_supplier, make_price, make_user, make_session
):
    material = make_material()
    supplier = make_supplier()
    price = make_price(material, supplier, price=15.0)
    client = _admin_client(make_user, make_session)

    response = client.get(f"/prices/{price.id}")

    assert response.status_code == 200
    assert response.json()["price"] == 15.0


def test_get_price_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.get(f"/prices/{uuid.uuid4()}")

    assert response.status_code == 404


def test_list_prices_filters_by_material_id(
    db_session, make_material, make_supplier, make_price, make_user, make_session
):
    material_a = make_material()
    material_b = make_material()
    supplier = make_supplier()
    price_a = make_price(material_a, supplier, price=1.0)
    make_price(material_b, supplier, price=2.0)
    client = _admin_client(make_user, make_session)

    response = client.get("/prices", params={"material_id": str(material_a.id)})

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert ids == [str(price_a.id)]


def test_update_price_closes_old_row_and_creates_new_one(
    db_session, make_material, make_supplier, make_price, make_user, make_session
):
    material = make_material()
    supplier = make_supplier()
    old_price = make_price(material, supplier, price=10.0)
    today = datetime.date.today()
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/prices/{old_price.id}",
        json={
            "price": 20.0,
            "currency": "USD",
            "availability": 50,
            "min_order_qty": 2,
            "valid_from": str(today),
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] != str(old_price.id)
    assert body["price"] == 20.0
    assert body["valid_to"] is None

    old_response = client.get(f"/prices/{old_price.id}")
    assert old_response.json()["valid_to"] == str(today)


def test_update_price_partial_payload_inherits_omitted_fields_from_existing(
    db_session, make_material, make_supplier, make_price, make_user, make_session
):
    material = make_material()
    supplier = make_supplier()
    old_price = make_price(
        material, supplier, price=10.0, availability=42, min_order_qty=7
    )
    today = datetime.date.today()
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/prices/{old_price.id}",
        json={"price": 20.0, "valid_from": str(today)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["price"] == 20.0
    assert body["currency"] == "USD"
    assert body["availability"] == 42
    assert body["min_order_qty"] == 7


def test_create_price_rejects_negative_availability(
    db_session, make_material, make_supplier, make_user, make_session
):
    material = make_material()
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/prices",
        json={
            "material_id": str(material.id),
            "supplier_id": str(supplier.id),
            "price": 10.0,
            "availability": -1,
            "valid_from": str(datetime.date.today()),
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_create_price_rejects_negative_min_order_qty(
    db_session, make_material, make_supplier, make_user, make_session
):
    material = make_material()
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/prices",
        json={
            "material_id": str(material.id),
            "supplier_id": str(supplier.id),
            "price": 10.0,
            "min_order_qty": -1,
            "valid_from": str(datetime.date.today()),
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_update_price_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/prices/{uuid.uuid4()}",
        json={"price": 1.0, "valid_from": str(datetime.date.today())},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_delete_price_removes_it(
    db_session, make_material, make_supplier, make_price, make_user, make_session
):
    material = make_material()
    supplier = make_supplier()
    price = make_price(material, supplier)
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/prices/{price.id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 204
    assert client.get(f"/prices/{price.id}").status_code == 404


def test_delete_price_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/prices/{uuid.uuid4()}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 404


def test_delete_price_returns_409_for_closed_historical_price(
    db_session, make_material, make_supplier, make_price, make_user, make_session
):
    material = make_material()
    supplier = make_supplier()
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    closed_price = make_price(
        material, supplier, price=5.0, valid_from=yesterday, valid_to=yesterday
    )
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/prices/{closed_price.id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 409
    assert client.get(f"/prices/{closed_price.id}").status_code == 200


def test_list_prices_no_session_returns_401():
    client = TestClient(app)
    response = client.get("/prices")
    assert response.status_code == 401


def test_list_prices_as_employee_returns_403(make_user, make_session):
    employee = make_user(role="employee")
    employee_session = make_session(employee)
    response = _client_as(employee_session).get("/prices")
    assert response.status_code == 403


def test_list_prices_as_admin_succeeds(make_user, make_session):
    admin = make_user(email="admin-price-list@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin)
    response = _client_as(admin_session).get("/prices")
    assert response.status_code == 200
