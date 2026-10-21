"""Tests for POST /orders/{order_id}/response-aliases and
DELETE /suppliers/{supplier_id}/aliases/{alias_id} — see ADR-0046 §2.
"""

import uuid

from app.models import SupplierMaterialAlias

CSRF = "test-csrf-token"
_employee_counter = [0]
_admin_counter = [0]


def _client_as(user_session):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def _employee_client(make_user, make_session):
    _employee_counter[0] += 1
    email = f"employee-alias{_employee_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session), employee


def _admin_client(make_user, make_session):
    _admin_counter[0] += 1
    email = f"admin-alias{_admin_counter[0]}@screen-factory-florida.com"
    admin = make_user(email=email, role="admin")
    admin_session = make_session(admin, csrf_token=CSRF)
    return _client_as(admin_session), admin


def _post_alias(client, order_id, **body):
    return client.post(
        f"/orders/{order_id}/response-aliases",
        json=body,
        headers={"X-CSRF-Token": CSRF},
    )


def _delete_alias(client, supplier_id, alias_id):
    return client.delete(
        f"/suppliers/{supplier_id}/aliases/{alias_id}",
        headers={"X-CSRF-Token": CSRF},
    )


def test_create_alias_employee_can_do_it_and_origin_is_order_response(
    db_session, make_supplier, make_material, make_order, make_user, make_session
):
    """ADR-0046 §5: the whole order.py router is open to 'employee', not
    just 'admin' — creating a response-alias from the order-response
    review screen must not be more restricted than the rest of that
    screen."""
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material()
    order = make_order(supplier, [(material, 4, 2.52)])
    client, employee = _employee_client(make_user, make_session)

    response = _post_alias(
        client,
        order.id,
        supplier_raw_name="S-25-00-00070 3X4 A ELBOW BRONZE",
        supplier_sku=None,
        material_id=str(material.id),
    )

    assert response.status_code == 200
    alias = (
        session.query(SupplierMaterialAlias)
        .filter_by(supplier_id=supplier.id, material_id=material.id)
        .one()
    )
    assert alias.origin == "order_response"
    assert alias.supplier_raw_name == "S-25-00-00070 3X4 A ELBOW BRONZE"
    assert alias.created_by_user_id == employee.id
    assert alias.created_at is not None


def test_create_alias_order_not_found_returns_404(
    db_session, make_material, make_user, make_session
):
    session, *_ = db_session
    material = make_material()
    client, _employee = _employee_client(make_user, make_session)

    response = _post_alias(
        client,
        uuid.uuid4(),
        supplier_raw_name="whatever",
        supplier_sku=None,
        material_id=str(material.id),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"


def test_create_alias_material_not_found_returns_404(
    db_session, make_supplier, make_material, make_order, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material()
    order = make_order(supplier, [(material, 4, 2.52)])
    client, _employee = _employee_client(make_user, make_session)

    response = _post_alias(
        client,
        order.id,
        supplier_raw_name="whatever",
        supplier_sku=None,
        material_id=str(uuid.uuid4()),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Material not found"


def test_create_alias_idempotent_on_exact_triple(
    db_session, make_supplier, make_material, make_order, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material()
    order = make_order(supplier, [(material, 4, 2.52)])
    client, _employee = _employee_client(make_user, make_session)

    first = _post_alias(
        client,
        order.id,
        supplier_raw_name="S-25-00-00070 3X4 A ELBOW BRONZE",
        supplier_sku=None,
        material_id=str(material.id),
    )
    second = _post_alias(
        client,
        order.id,
        supplier_raw_name="S-25-00-00070 3X4 A ELBOW BRONZE",
        supplier_sku=None,
        material_id=str(material.id),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    count = (
        session.query(SupplierMaterialAlias)
        .filter_by(
            supplier_id=supplier.id,
            material_id=material.id,
            supplier_raw_name="S-25-00-00070 3X4 A ELBOW BRONZE",
            origin="order_response",
        )
        .count()
    )
    assert count == 1


def test_create_alias_conflict_without_force_returns_409(
    db_session, make_supplier, make_material, make_order, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material_a = make_material(canonical_name="Material A")
    material_b = make_material(canonical_name="Material B")
    order = make_order(supplier, [(material_a, 1, 1.0), (material_b, 1, 1.0)])
    client, _employee = _employee_client(make_user, make_session)

    _post_alias(
        client,
        order.id,
        supplier_raw_name="Ambiguous Raw Name",
        supplier_sku=None,
        material_id=str(material_a.id),
    )
    response = _post_alias(
        client,
        order.id,
        supplier_raw_name="Ambiguous Raw Name",
        supplier_sku=None,
        material_id=str(material_b.id),
    )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["existing"]["material_id"] == str(material_a.id)

    count = (
        session.query(SupplierMaterialAlias)
        .filter_by(supplier_id=supplier.id, supplier_raw_name="Ambiguous Raw Name")
        .count()
    )
    assert count == 1


def test_create_alias_conflict_with_force_overwrites(
    db_session, make_supplier, make_material, make_order, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material_a = make_material(canonical_name="Material A")
    material_b = make_material(canonical_name="Material B")
    order = make_order(supplier, [(material_a, 1, 1.0), (material_b, 1, 1.0)])
    client, _employee = _employee_client(make_user, make_session)

    _post_alias(
        client,
        order.id,
        supplier_raw_name="Ambiguous Raw Name",
        supplier_sku=None,
        material_id=str(material_a.id),
    )
    response = _post_alias(
        client,
        order.id,
        supplier_raw_name="Ambiguous Raw Name",
        supplier_sku=None,
        material_id=str(material_b.id),
        force=True,
    )

    assert response.status_code == 200
    rows = (
        session.query(SupplierMaterialAlias)
        .filter_by(supplier_id=supplier.id, supplier_raw_name="Ambiguous Raw Name")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].material_id == material_b.id
    assert rows[0].origin == "order_response"
    assert response.json()["origin"] == "order_response"


def test_delete_alias_requires_admin(
    db_session, make_supplier, make_material, make_alias, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material()
    alias = make_alias(supplier, material, "Raw Name")
    client, _employee = _employee_client(make_user, make_session)

    response = _delete_alias(client, supplier.id, alias.id)

    assert response.status_code == 403


def test_delete_alias_admin_succeeds(
    db_session, make_supplier, make_material, make_alias, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material()
    alias = make_alias(supplier, material, "Raw Name")
    client, _admin = _admin_client(make_user, make_session)

    response = _delete_alias(client, supplier.id, alias.id)

    assert response.status_code == 204
    assert session.get(SupplierMaterialAlias, alias.id) is None


def test_delete_alias_wrong_supplier_in_path_returns_404(
    db_session, make_supplier, make_material, make_alias, make_user, make_session
):
    session, *_ = db_session
    supplier_a = make_supplier(name="Supplier A")
    supplier_b = make_supplier(name="Supplier B")
    material = make_material()
    alias = make_alias(supplier_a, material, "Raw Name")
    client, _admin = _admin_client(make_user, make_session)

    response = _delete_alias(client, supplier_b.id, alias.id)

    assert response.status_code == 404
    assert response.json()["detail"] == "Alias not found"
    assert session.get(SupplierMaterialAlias, alias.id) is not None


def test_delete_alias_refuses_price_import_origin(
    db_session, make_supplier, make_material, make_alias, make_user, make_session
):
    """ADR-0046 §5: this endpoint only ever removes origin='order_response'
    aliases — it exists to undo a mistaken "Связать" click, not to manage
    price-ingestion's vocabulary. A price_import-origin alias, even with a
    correct supplier_id/alias_id pair, is treated as not found (same
    reasoning as the 404 for a wrong supplier_id: this endpoint has no
    business touching that row). The SQL recipe in ADR-0046 §6/known-
    issues.md is the only path for removing a price_import alias."""
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material()
    alias = make_alias(supplier, material, "Raw Name", origin="price_import")

    client, _admin = _admin_client(make_user, make_session)

    response = _delete_alias(client, supplier.id, alias.id)

    assert response.status_code == 404
    assert response.json()["detail"] == "Alias not found"
    assert session.get(SupplierMaterialAlias, alias.id) is not None
