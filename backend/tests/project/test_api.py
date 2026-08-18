import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_list_projects_returns_projects_ordered_by_created_at_desc(make_project):
    older = make_project(title="Older Project")
    newer = make_project(title="Newer Project")

    response = client.get("/projects")

    assert response.status_code == 200
    body = response.json()
    ids = [row["id"] for row in body]
    assert ids.index(str(newer.id)) < ids.index(str(older.id))


def test_create_project_returns_201_with_body(db_session):
    session, project_ids, _material_ids = db_session

    response = client.post("/projects", json={"title": "Riverside Pool Cage"})

    assert response.status_code == 201
    body = response.json()
    project_ids.append(uuid.UUID(body["id"]))
    assert body["title"] == "Riverside Pool Cage"
    assert body["status"] == "draft"
    assert body["created_by"] is None


def test_update_project_changes_title(make_project):
    project = make_project(title="Original Title")

    response = client.patch(f"/projects/{project.id}", json={"title": "Renamed Project"})

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed Project"

    get_response = client.get(f"/projects/{project.id}")
    assert get_response.json()["title"] == "Renamed Project"


def test_update_project_returns_404_for_missing_project():
    response = client.patch(f"/projects/{uuid.uuid4()}", json={"title": "Doesn't matter"})

    assert response.status_code == 404


def test_get_project_returns_created_project_with_items(db_session, make_project, make_material):
    project = make_project(title="Get Me")
    material = make_material()
    session, _project_ids, _material_ids = db_session

    response = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 5},
    )
    assert response.status_code == 201

    response = client.get(f"/projects/{project.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Get Me"
    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 5
    assert body["items"][0]["material_id"] == str(material.id)


def test_get_project_returns_404_for_missing_project():
    response = client.get(f"/projects/{uuid.uuid4()}")

    assert response.status_code == 404


def test_add_project_item_returns_404_for_missing_project(make_material):
    material = make_material()

    response = client.post(
        f"/projects/{uuid.uuid4()}/items",
        json={"material_id": str(material.id), "quantity": 1},
    )

    assert response.status_code == 404


def test_add_project_item_returns_404_for_missing_material(make_project):
    project = make_project()

    response = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(uuid.uuid4()), "quantity": 1},
    )

    assert response.status_code == 404


def test_add_project_item_rejects_non_positive_quantity(make_project, make_material):
    project = make_project()
    material = make_material()

    response = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 0},
    )

    assert response.status_code == 422


def test_update_project_item_changes_quantity(make_project, make_material):
    project = make_project()
    material = make_material()
    create_response = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 5},
    )
    item_id = create_response.json()["id"]

    response = client.patch(
        f"/projects/{project.id}/items/{item_id}",
        json={"quantity": 12},
    )

    assert response.status_code == 200
    assert response.json()["quantity"] == 12


def test_update_project_item_rejects_non_positive_quantity(make_project, make_material):
    project = make_project()
    material = make_material()
    create_response = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 5},
    )
    item_id = create_response.json()["id"]

    response = client.patch(
        f"/projects/{project.id}/items/{item_id}",
        json={"quantity": 0},
    )

    assert response.status_code == 422


def test_update_project_item_returns_404_for_item_from_another_project(
    make_project, make_material
):
    project_a = make_project()
    project_b = make_project()
    material = make_material()
    create_response = client.post(
        f"/projects/{project_a.id}/items",
        json={"material_id": str(material.id), "quantity": 5},
    )
    item_id = create_response.json()["id"]

    response = client.patch(
        f"/projects/{project_b.id}/items/{item_id}",
        json={"quantity": 9},
    )

    assert response.status_code == 404


def test_delete_project_item_removes_it(make_project, make_material):
    project = make_project()
    material = make_material()
    create_response = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 5},
    )
    item_id = create_response.json()["id"]

    response = client.delete(f"/projects/{project.id}/items/{item_id}")

    assert response.status_code == 204
    get_response = client.get(f"/projects/{project.id}")
    assert get_response.json()["items"] == []


def test_delete_project_item_returns_404_for_missing_item(make_project):
    project = make_project()

    response = client.delete(f"/projects/{project.id}/items/{uuid.uuid4()}")

    assert response.status_code == 404


def test_add_project_item_allows_same_material_in_two_items(make_project, make_material):
    """Duplicate material across rows is allowed as separate ProjectItem rows —
    see ui-reference.md §2 open question, resolved as "allow" for this screen."""
    project = make_project()
    material = make_material()

    first = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 3},
    )
    second = client.post(
        f"/projects/{project.id}/items",
        json={"material_id": str(material.id), "quantity": 7},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
