import uuid

from fastapi.testclient import TestClient

from app.main import app

CSRF = "test-csrf-token"


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


_employee_email_counter = [0]


def _employee_client(make_user, make_session):
    _employee_email_counter[0] += 1
    email = f"employee-project{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session)


def test_list_projects_returns_projects_ordered_by_created_at_desc(
    make_project, make_user, make_session
):
    older = make_project(title="Older Project")
    newer = make_project(title="Newer Project")
    client = _employee_client(make_user, make_session)

    response = client.get("/projects")

    assert response.status_code == 200
    body = response.json()
    ids = [row["id"] for row in body]
    assert ids.index(str(newer.id)) < ids.index(str(older.id))


def test_create_project_returns_201_with_body(db_session, make_user, make_session):
    session, project_ids, _material_ids, _supplier_ids, _user_ids = db_session
    employee_email = "employee-project-create@screen-factory-florida.com"
    employee = make_user(email=employee_email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    client = _client_as(employee_session)

    response = client.post(
        "/projects", json={"title": "Riverside Pool Cage"}, headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 201
    body = response.json()
    project_ids.append(uuid.UUID(body["id"]))
    assert body["title"] == "Riverside Pool Cage"
    assert body["status"] == "draft"
    assert body["created_by_user_id"] == str(employee.id)


def test_update_project_changes_title(make_project, make_user, make_session):
    project = make_project(title="Original Title")
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/projects/{project.id}",
        json={"title": "Renamed Project"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed Project"

    get_response = client.get(f"/projects/{project.id}")
    assert get_response.json()["title"] == "Renamed Project"


def test_update_project_returns_404_for_missing_project(make_user, make_session):
    client = _employee_client(make_user, make_session)

    response = client.patch(
        f"/projects/{uuid.uuid4()}",
        json={"title": "Doesn't matter"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_get_project_returns_created_project_with_items(
    db_session, make_project, make_material, make_user, make_session
):
    project = make_project(title="Get Me")
    material = make_material()
    session, _project_ids, _material_ids, _supplier_ids, _user_ids = db_session
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 5},
        headers={"X-CSRF-Token": CSRF},
    )
    assert response.status_code == 201

    response = client.get(f"/projects/{project.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Get Me"
    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 5
    assert body["items"][0]["material_id"] == str(material.id)


def test_get_project_returns_404_for_missing_project(make_user, make_session):
    client = _employee_client(make_user, make_session)

    response = client.get(f"/projects/{uuid.uuid4()}")

    assert response.status_code == 404


def test_add_project_item_returns_404_for_missing_project(
    make_material, make_user, make_session
):
    material = make_material()
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{uuid.uuid4()}/items",
        json={"material_id": str(material.id), "quantity": 1},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_add_project_item_returns_404_for_missing_material(make_project, make_user, make_session):
    project = make_project()
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(uuid.uuid4()), "quantity": 1},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_add_project_item_rejects_non_positive_quantity(
    make_project, make_material, make_user, make_session
):
    project = make_project()
    material = make_material()
    client = _employee_client(make_user, make_session)

    response = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 0},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_update_project_item_changes_quantity(
    make_project, make_material, make_user, make_session
):
    project = make_project()
    material = make_material()
    client = _employee_client(make_user, make_session)
    create_response = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 5},
        headers={"X-CSRF-Token": CSRF},
    )
    item_id = create_response.json()["id"]

    response = client.patch(
        f"/projects/{project.id}/items/{item_id}",
        json={"quantity": 12},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["quantity"] == 12


def test_update_project_item_rejects_non_positive_quantity(
    make_project, make_material, make_user, make_session
):
    project = make_project()
    material = make_material()
    client = _employee_client(make_user, make_session)
    create_response = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 5},
        headers={"X-CSRF-Token": CSRF},
    )
    item_id = create_response.json()["id"]

    response = client.patch(
        f"/projects/{project.id}/items/{item_id}",
        json={"quantity": 0},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_update_project_item_returns_404_for_item_from_another_project(
    make_project, make_material, make_user, make_session
):
    project_a = make_project()
    project_b = make_project()
    material = make_material()
    client = _employee_client(make_user, make_session)
    create_response = client.post(
        f"/projects/{project_a.id}/items",
        json={"material_id": str(material.id), "quantity": 5},
        headers={"X-CSRF-Token": CSRF},
    )
    item_id = create_response.json()["id"]

    response = client.patch(
        f"/projects/{project_b.id}/items/{item_id}",
        json={"quantity": 9},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_delete_project_item_removes_it(make_project, make_material, make_user, make_session):
    project = make_project()
    material = make_material()
    client = _employee_client(make_user, make_session)
    create_response = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 5},
        headers={"X-CSRF-Token": CSRF},
    )
    item_id = create_response.json()["id"]

    response = client.delete(
        f"/projects/{project.id}/items/{item_id}", headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 204
    get_response = client.get(f"/projects/{project.id}")
    assert get_response.json()["items"] == []


def test_delete_project_item_returns_404_for_missing_item(make_project, make_user, make_session):
    project = make_project()
    client = _employee_client(make_user, make_session)

    response = client.delete(
        f"/projects/{project.id}/items/{uuid.uuid4()}", headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 404


def test_add_project_item_allows_same_material_in_two_items(
    make_project, make_material, make_user, make_session
):
    """Duplicate material across rows is allowed as separate ProjectItem rows —
    see ui-reference.md §2 open question, resolved as "allow" for this screen."""
    project = make_project()
    material = make_material()
    client = _employee_client(make_user, make_session)

    first = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 3},
        headers={"X-CSRF-Token": CSRF},
    )
    second = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 7},
        headers={"X-CSRF-Token": CSRF},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


def test_list_projects_no_session_returns_401():
    client = TestClient(app)
    response = client.get("/projects")
    assert response.status_code == 401


def test_create_project_as_employee_succeeds(db_session, make_user, make_session):
    session, project_ids, _material_ids, _supplier_ids, _user_ids = db_session
    employee = make_user(role="employee", email="employee-proj-create2@screen-factory-florida.com")
    employee_session = make_session(employee, csrf_token=CSRF)
    client = _client_as(employee_session)
    response = client.post(
        "/projects",
        json={"title": "New Project"},
        headers={"X-CSRF-Token": CSRF},
    )
    assert response.status_code == 201
    body = response.json()
    project_ids.append(uuid.UUID(body["id"]))
    assert body["created_by_user_id"] == str(employee.id)
