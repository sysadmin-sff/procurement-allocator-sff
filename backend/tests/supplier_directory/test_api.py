"""Tests for Office / SupplierContact CRUD and Supplier directory fields — ADR-0010.

Covers: Office/SupplierContact CRUD, nullable office_id on a contact, 422 when
a contact is attached to an office belonging to a different supplier, Office
deletion sets office_id to NULL on its contacts (not RESTRICT — see
app/supplier_directory/service.py module docstring for rationale), new scalar
Supplier fields under PATCH semantics, GET /suppliers/{id} returning offices
and contacts nested, and 404s for unknown ids / cross-supplier mismatches.
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

CSRF = "test-csrf-token"

_admin_email_counter = [0]


def _admin_client(make_user, make_session):
    _admin_email_counter[0] += 1
    email = f"admin-supplier-directory{_admin_email_counter[0]}@screen-factory-florida.com"
    admin = make_user(email=email, role="admin")
    admin_session = make_session(admin, csrf_token=CSRF)
    client = TestClient(app)
    client.cookies.set("session_id", str(admin_session.id))
    return client


# --- Office CRUD ---


def test_create_office_via_api(db_session, make_supplier, make_user, make_session):
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    response = client.post(
        f"/suppliers/{supplier.id}/offices",
        json={"address": "100 Industrial Way, Tampa FL", "region": "West Coast of Florida"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["address"] == "100 Industrial Way, Tampa FL"
    assert body["region"] == "West Coast of Florida"
    assert body["supplier_id"] == str(supplier.id)


def test_create_office_returns_404_for_unknown_supplier(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.post(
        f"/suppliers/{uuid.uuid4()}/offices",
        json={"address": "100 Industrial Way"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_update_office_partial_payload_preserves_omitted_fields(
    db_session, make_supplier, make_office, make_user, make_session
):
    supplier = make_supplier()
    office = make_office(supplier, address="Original Address", region="Original Region")
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/suppliers/{supplier.id}/offices/{office.id}",
        json={"address": "New Address"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["address"] == "New Address"
    assert body["region"] == "Original Region"


def test_update_office_returns_404_for_unknown_office(
    db_session, make_supplier, make_user, make_session
):
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/suppliers/{supplier.id}/offices/{uuid.uuid4()}",
        json={"address": "X"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_update_office_returns_404_when_office_belongs_to_different_supplier(
    db_session, make_supplier, make_office, make_user, make_session
):
    supplier_a = make_supplier(name="A")
    supplier_b = make_supplier(name="B")
    office = make_office(supplier_a)
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/suppliers/{supplier_b.id}/offices/{office.id}",
        json={"address": "X"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_delete_office_removes_it(db_session, make_supplier, make_office, make_user, make_session):
    supplier = make_supplier()
    office = make_office(supplier)
    client = _admin_client(make_user, make_session)

    response = client.delete(
        f"/suppliers/{supplier.id}/offices/{office.id}", headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 204
    get_response = client.get(f"/suppliers/{supplier.id}")
    assert get_response.json()["offices"] == []


def test_delete_office_returns_404_for_unknown_office(
    db_session, make_supplier, make_user, make_session
):
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    response = client.delete(
        f"/suppliers/{supplier.id}/offices/{uuid.uuid4()}", headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 404


def test_delete_office_sets_contact_office_id_to_null(
    db_session, make_supplier, make_office, make_user, make_session
):
    """Deleting an Office does not delete or block on its contacts — office_id
    is nullable and represents an optional attribution, see ADR-0010 п.2 and
    the service module docstring for why SET NULL (not RESTRICT) was chosen."""
    supplier = make_supplier()
    office = make_office(supplier)
    client = _admin_client(make_user, make_session)
    contact_response = client.post(
        f"/suppliers/{supplier.id}/contacts",
        json={"name": "Jane Doe", "office_id": str(office.id)},
        headers={"X-CSRF-Token": CSRF},
    )
    assert contact_response.status_code == 201
    contact_id = contact_response.json()["id"]

    delete_response = client.delete(
        f"/suppliers/{supplier.id}/offices/{office.id}", headers={"X-CSRF-Token": CSRF}
    )
    assert delete_response.status_code == 204

    get_response = client.get(f"/suppliers/{supplier.id}")
    contact = next(
        c for c in get_response.json()["supplier_contacts"] if c["id"] == contact_id
    )
    assert contact["office_id"] is None


# --- SupplierContact CRUD ---


def test_create_contact_without_office_id(db_session, make_supplier, make_user, make_session):
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    response = client.post(
        f"/suppliers/{supplier.id}/contacts",
        json={"name": "General Orders", "role": None, "phone": None, "email": "orders@x.com"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["office_id"] is None
    assert body["email"] == "orders@x.com"


def test_create_contact_with_office_id(
    db_session, make_supplier, make_office, make_user, make_session
):
    supplier = make_supplier()
    office = make_office(supplier)
    client = _admin_client(make_user, make_session)

    response = client.post(
        f"/suppliers/{supplier.id}/contacts",
        json={
            "name": "Jane Doe",
            "role": "Inside Sales Representative",
            "office_id": str(office.id),
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["office_id"] == str(office.id)
    assert body["role"] == "Inside Sales Representative"


def test_create_contact_returns_404_for_unknown_supplier(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.post(
        f"/suppliers/{uuid.uuid4()}/contacts",
        json={"name": "X"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_create_contact_rejects_office_from_different_supplier(
    db_session, make_supplier, make_office, make_user, make_session
):
    supplier_a = make_supplier(name="A")
    supplier_b = make_supplier(name="B")
    office_of_b = make_office(supplier_b)
    client = _admin_client(make_user, make_session)

    response = client.post(
        f"/suppliers/{supplier_a.id}/contacts",
        json={"name": "Jane Doe", "office_id": str(office_of_b.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_create_contact_rejects_nonexistent_office_id(
    db_session, make_supplier, make_user, make_session
):
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    response = client.post(
        f"/suppliers/{supplier.id}/contacts",
        json={"name": "Jane Doe", "office_id": str(uuid.uuid4())},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_update_contact_partial_payload_preserves_omitted_fields(
    db_session, make_supplier, make_user, make_session
):
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)
    create_response = client.post(
        f"/suppliers/{supplier.id}/contacts",
        json={"name": "Jane Doe", "role": "Credit department", "phone": "555-1234"},
        headers={"X-CSRF-Token": CSRF},
    )
    contact_id = create_response.json()["id"]

    response = client.patch(
        f"/suppliers/{supplier.id}/contacts/{contact_id}",
        json={"phone": "555-9999"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "555-9999"
    assert body["name"] == "Jane Doe"
    assert body["role"] == "Credit department"


def test_update_contact_can_attach_office(
    db_session, make_supplier, make_office, make_user, make_session
):
    supplier = make_supplier()
    office = make_office(supplier)
    client = _admin_client(make_user, make_session)
    create_response = client.post(
        f"/suppliers/{supplier.id}/contacts",
        json={"name": "Jane Doe"},
        headers={"X-CSRF-Token": CSRF},
    )
    contact_id = create_response.json()["id"]

    response = client.patch(
        f"/suppliers/{supplier.id}/contacts/{contact_id}",
        json={"office_id": str(office.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["office_id"] == str(office.id)


def test_update_contact_rejects_office_from_different_supplier(
    db_session, make_supplier, make_office, make_user, make_session
):
    supplier_a = make_supplier(name="A")
    supplier_b = make_supplier(name="B")
    office_of_b = make_office(supplier_b)
    client = _admin_client(make_user, make_session)
    create_response = client.post(
        f"/suppliers/{supplier_a.id}/contacts",
        json={"name": "Jane Doe"},
        headers={"X-CSRF-Token": CSRF},
    )
    contact_id = create_response.json()["id"]

    response = client.patch(
        f"/suppliers/{supplier_a.id}/contacts/{contact_id}",
        json={"office_id": str(office_of_b.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_update_contact_returns_404_for_unknown_contact(
    db_session, make_supplier, make_user, make_session
):
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/suppliers/{supplier.id}/contacts/{uuid.uuid4()}",
        json={"name": "X"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_update_contact_returns_404_when_contact_belongs_to_different_supplier(
    db_session, make_supplier, make_user, make_session
):
    supplier_a = make_supplier(name="A")
    supplier_b = make_supplier(name="B")
    client = _admin_client(make_user, make_session)
    create_response = client.post(
        f"/suppliers/{supplier_a.id}/contacts",
        json={"name": "Jane Doe"},
        headers={"X-CSRF-Token": CSRF},
    )
    contact_id = create_response.json()["id"]

    response = client.patch(
        f"/suppliers/{supplier_b.id}/contacts/{contact_id}",
        json={"name": "X"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_delete_contact_removes_it(db_session, make_supplier, make_user, make_session):
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)
    create_response = client.post(
        f"/suppliers/{supplier.id}/contacts",
        json={"name": "Jane Doe"},
        headers={"X-CSRF-Token": CSRF},
    )
    contact_id = create_response.json()["id"]

    response = client.delete(
        f"/suppliers/{supplier.id}/contacts/{contact_id}", headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 204
    get_response = client.get(f"/suppliers/{supplier.id}")
    assert get_response.json()["supplier_contacts"] == []


def test_delete_contact_returns_404_for_unknown_contact(
    db_session, make_supplier, make_user, make_session
):
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    response = client.delete(
        f"/suppliers/{supplier.id}/contacts/{uuid.uuid4()}", headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 404


# --- Supplier scalar fields (PATCH semantics) ---


def test_create_supplier_with_new_scalar_fields(db_session, make_user, make_session):
    session, supplier_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/suppliers",
        json={"name": "Eastern Metal Supply"},
        headers={"X-CSRF-Token": CSRF},
    )
    assert response.status_code == 201
    supplier_id = response.json()["id"]
    supplier_ids.append(uuid.UUID(supplier_id))

    response = client.put(
        f"/suppliers/{supplier_id}",
        json={
            "website": "https://easternmetal.com",
            "region": "Florida",
            "catalog_link": "https://drive.google.com/x",
            "status": "Активные закупки",
            "payment_terms": "NET 30",
            "portal_url": "https://portal.easternmetal.com",
            "comments": "Prices updated quarterly.",
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["website"] == "https://easternmetal.com"
    assert body["region"] == "Florida"
    assert body["catalog_link"] == "https://drive.google.com/x"
    assert body["status"] == "Активные закупки"
    assert body["payment_terms"] == "NET 30"
    assert body["portal_url"] == "https://portal.easternmetal.com"
    assert body["comments"] == "Prices updated quarterly."


def test_update_supplier_new_fields_partial_payload_preserves_omitted_fields(
    db_session, make_supplier, make_user, make_session
):
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)
    client.put(
        f"/suppliers/{supplier.id}",
        json={"website": "https://old.example.com", "payment_terms": "NET 15"},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.put(
        f"/suppliers/{supplier.id}",
        json={"payment_terms": "NET 30"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["payment_terms"] == "NET 30"
    assert body["website"] == "https://old.example.com"


def test_supplier_short_name_defaults_to_null_and_is_settable_via_patch(
    db_session, make_supplier, make_user, make_session
):
    """ADR-0017: short_name is nullable, absent from SupplierCreate (п.4),
    editable via PUT /suppliers/{id} like the rest of ADR-0010's scalar fields."""
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)
    assert client.get(f"/suppliers/{supplier.id}").json()["short_name"] is None

    response = client.put(
        f"/suppliers/{supplier.id}",
        json={"short_name": "ADI LLC"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["short_name"] == "ADI LLC"


# --- GET /suppliers/{id} nested offices/contacts ---


def test_get_supplier_returns_offices_and_contacts_nested(
    db_session, make_supplier, make_office, make_user, make_session
):
    supplier = make_supplier()
    office = make_office(supplier, address="1 Office Rd", region="North FL")
    client = _admin_client(make_user, make_session)
    client.post(
        f"/suppliers/{supplier.id}/contacts",
        json={"name": "Jane Doe", "office_id": str(office.id)},
        headers={"X-CSRF-Token": CSRF},
    )
    client.post(
        f"/suppliers/{supplier.id}/contacts",
        json={"name": "No Office Contact"},
        headers={"X-CSRF-Token": CSRF},
    )

    response = client.get(f"/suppliers/{supplier.id}")

    assert response.status_code == 200
    body = response.json()
    assert len(body["offices"]) == 1
    assert body["offices"][0]["address"] == "1 Office Rd"
    assert len(body["supplier_contacts"]) == 2
    names = {c["name"] for c in body["supplier_contacts"]}
    assert names == {"Jane Doe", "No Office Contact"}


def test_get_supplier_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.get(f"/suppliers/{uuid.uuid4()}")

    assert response.status_code == 404


# --- Auth boundary ---


def test_list_offices_no_session_returns_401(make_supplier):
    supplier = make_supplier()
    client = TestClient(app)

    response = client.get(f"/suppliers/{supplier.id}")

    assert response.status_code == 401


def test_supplier_directory_as_employee_returns_403(make_supplier, make_user, make_session):
    supplier = make_supplier()
    employee = make_user(role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    client = TestClient(app)
    client.cookies.set("session_id", str(employee_session.id))

    response = client.get(f"/suppliers/{supplier.id}")

    assert response.status_code == 403
