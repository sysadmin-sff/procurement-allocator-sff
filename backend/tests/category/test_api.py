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
    email = f"admin-category{_admin_email_counter[0]}@screen-factory-florida.com"
    admin = make_user(email=email, role="admin")
    admin_session = make_session(admin, csrf_token=CSRF)
    return _client_as(admin_session)


# --- admin-only ---


def test_list_categories_no_session_returns_401():
    client = TestClient(app)
    response = client.get("/categories")
    assert response.status_code == 401


def test_list_categories_as_employee_returns_403(make_user, make_session):
    employee = make_user(role="employee")
    employee_session = make_session(employee)
    response = _client_as(employee_session).get("/categories")
    assert response.status_code == 403


def test_create_category_as_employee_returns_403(make_user, make_session):
    employee = make_user(email="employee-create@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    response = _client_as(employee_session).post(
        "/categories",
        json={"name": "TestX", "sku_prefix": "TSTX"},
        headers={"X-CSRF-Token": CSRF},
    )
    assert response.status_code == 403


def test_patch_category_as_employee_returns_403(make_category, make_user, make_session):
    category = make_category()
    employee = make_user(email="employee-patch@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    response = _client_as(employee_session).patch(
        f"/categories/{category.id}", json={"name": "Y"}, headers={"X-CSRF-Token": CSRF}
    )
    assert response.status_code == 403


def test_delete_category_as_employee_returns_403(make_category, make_user, make_session):
    category = make_category()
    employee = make_user(email="employee-delete@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    response = _client_as(employee_session).delete(
        f"/categories/{category.id}", headers={"X-CSRF-Token": CSRF}
    )
    assert response.status_code == 403


def test_no_session_returns_401_on_all_mutating_paths(make_category):
    category = make_category()
    client = TestClient(app)

    assert (
        client.post("/categories", json={"name": "X", "sku_prefix": "XXXX"}).status_code == 401
    )
    assert client.patch(f"/categories/{category.id}", json={"name": "Y"}).status_code == 401
    assert client.delete(f"/categories/{category.id}").status_code == 401


# --- CRUD ---


def test_create_category_returns_201(db_session, make_user, make_session):
    session, category_ids, _material_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/categories",
        json={"name": "TestDoorsCRUD", "sku_prefix": "TDCR", "requires_single_supplier": True},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    category_ids.append(uuid.UUID(body["id"]))
    assert body["name"] == "TestDoorsCRUD"
    assert body["sku_prefix"] == "TDCR"
    assert body["requires_single_supplier"] is True
    assert body["next_sku_number"] == 1


def test_create_category_defaults_requires_single_supplier_false(
    db_session, make_user, make_session
):
    session, category_ids, _material_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/categories",
        json={"name": "TestMiscCRUD", "sku_prefix": "TMSC"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    category_ids.append(uuid.UUID(body["id"]))
    assert body["requires_single_supplier"] is False


def test_create_category_returns_409_for_duplicate_name(
    db_session, make_category, make_user, make_session
):
    category = make_category(name="DupeNameCategory")
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/categories",
        json={"name": category.name, "sku_prefix": "OTHR"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409


def test_create_category_returns_409_for_duplicate_sku_prefix(
    db_session, make_category, make_user, make_session
):
    category = make_category(sku_prefix="DUPE")
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/categories",
        json={"name": "Different Name Entirely", "sku_prefix": category.sku_prefix},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409


def test_patch_category_renames(db_session, make_category, make_user, make_session):
    category = make_category(name="OldNameCategory")
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/categories/{category.id}",
        json={"name": "NewNameCategory"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "NewNameCategory"


def test_patch_category_toggles_requires_single_supplier(
    db_session, make_category, make_user, make_session
):
    category = make_category(requires_single_supplier=False)
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/categories/{category.id}",
        json={"requires_single_supplier": True},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["requires_single_supplier"] is True


def test_patch_category_rejects_sku_prefix_field(
    db_session, make_category, make_user, make_session
):
    """ADR-0034 п.5: sku_prefix is immutable -- CategoryUpdate has no field
    for it at all, so a client attempting to send it gets a hard validation
    error, not silent ignoring."""
    category = make_category(sku_prefix="ORIG")
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/categories/{category.id}",
        json={"sku_prefix": "HACKED"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_patch_category_returns_409_for_duplicate_name(
    db_session, make_category, make_user, make_session
):
    make_category(name="ExistingNameForPatch")
    other = make_category(name="OtherNameForPatch")
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/categories/{other.id}",
        json={"name": "ExistingNameForPatch"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409


def test_patch_category_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/categories/{uuid.uuid4()}", json={"name": "X"}, headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 404


def test_delete_empty_category_returns_204(db_session, make_category, make_user, make_session):
    session, category_ids, _material_ids, _user_ids = db_session
    category = make_category()
    category_ids.remove(category.id)
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/categories/{category.id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 204


def test_delete_category_with_materials_returns_409_with_count(
    db_session, make_category, make_material, make_user, make_session
):
    category = make_category(name="ReferencedCategory")
    make_material(category)
    make_material(category)
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/categories/{category.id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 409
    assert "2" in response.json()["detail"]


def test_delete_category_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/categories/{uuid.uuid4()}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 404


def test_list_categories_includes_created_category(
    db_session, make_category, make_user, make_session
):
    make_category(name="ListedTestCategory")
    client = _admin_client(make_user, make_session)

    response = client.get("/categories")

    assert response.status_code == 200
    names = [row["name"] for row in response.json()]
    assert "ListedTestCategory" in names
