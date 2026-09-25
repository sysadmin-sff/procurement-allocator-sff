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
    email = f"admin-template{_admin_email_counter[0]}@screen-factory-florida.com"
    admin = make_user(email=email, role="admin")
    admin_session = make_session(admin, csrf_token=CSRF)
    return _client_as(admin_session)


# --- admin-only ---


def test_list_templates_no_session_returns_401():
    client = TestClient(app)
    response = client.get("/project-templates")
    assert response.status_code == 401


def test_list_templates_as_employee_returns_403(make_user, make_session):
    employee = make_user(role="employee")
    employee_session = make_session(employee)
    response = _client_as(employee_session).get("/project-templates")
    assert response.status_code == 403


def test_create_template_as_employee_returns_403(make_user, make_session):
    employee = make_user(email="employee-create@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    response = _client_as(employee_session).post(
        "/project-templates", json={"name": "X"}, headers={"X-CSRF-Token": CSRF}
    )
    assert response.status_code == 403


def test_patch_template_as_employee_returns_403(make_template, make_user, make_session):
    template = make_template()
    employee = make_user(email="employee-patch@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    response = _client_as(employee_session).patch(
        f"/project-templates/{template.id}",
        json={"name": "Y"},
        headers={"X-CSRF-Token": CSRF},
    )
    assert response.status_code == 403


def test_delete_template_as_employee_returns_403(make_template, make_user, make_session):
    template = make_template()
    employee = make_user(email="employee-delete@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    response = _client_as(employee_session).delete(
        f"/project-templates/{template.id}", headers={"X-CSRF-Token": CSRF}
    )
    assert response.status_code == 403


def test_add_template_item_as_employee_returns_403(
    make_template, make_material, make_user, make_session
):
    template = make_template()
    material = make_material()
    employee = make_user(email="employee-additem@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    response = _client_as(employee_session).post(
        f"/project-templates/{template.id}/items",
        json={"material_id": str(material.id)},
        headers={"X-CSRF-Token": CSRF},
    )
    assert response.status_code == 403


def test_remove_template_item_as_employee_returns_403(
    make_template, make_material, make_user, make_session
):
    material = make_material()
    template = make_template(materials=[material])
    item_id = template.items[0].id
    employee = make_user(email="employee-removeitem@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    response = _client_as(employee_session).delete(
        f"/project-templates/{template.id}/items/{item_id}",
        headers={"X-CSRF-Token": CSRF},
    )
    assert response.status_code == 403


def test_no_session_returns_401_on_all_paths(make_template, make_material):
    material = make_material()
    template = make_template(materials=[material])
    item_id = template.items[0].id
    client = TestClient(app)

    assert client.get("/project-templates").status_code == 401
    assert client.post("/project-templates", json={"name": "X"}).status_code == 401
    assert (
        client.patch(f"/project-templates/{template.id}", json={"name": "Y"}).status_code == 401
    )
    assert client.delete(f"/project-templates/{template.id}").status_code == 401
    assert (
        client.post(
            f"/project-templates/{template.id}/items",
            json={"material_id": str(material.id)},
        ).status_code
        == 401
    )
    assert (
        client.delete(f"/project-templates/{template.id}/items/{item_id}").status_code == 401
    )


# --- CRUD cycle ---


def test_create_template_returns_201_with_empty_items(db_session, make_user, make_session):
    session, _material_ids, template_ids, _project_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/project-templates",
        json={"name": f"Standard Door {uuid.uuid4().hex[:8]}"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    template_ids.append(uuid.UUID(body["id"]))
    assert body["items"] == []


def test_create_template_returns_409_for_duplicate_name(
    db_session, make_template, make_user, make_session
):
    template = make_template()
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/project-templates", json={"name": template.name}, headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 409


def test_add_item_returns_template_with_denormalized_material_fields(
    db_session, make_template, make_material, make_category, make_user, make_session
):
    template = make_template()
    fencing = make_category(name="fencing", sku_prefix="FENC")
    material = make_material(canonical_name="6ft Vinyl Panel", unit="panel", category=fencing)
    client = _admin_client(make_user, make_session)

    response = client.post(
        f"/project-templates/{template.id}/items",
        json={"material_id": str(material.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["material_id"] == str(material.id)
    assert items[0]["canonical_name"] == "6ft Vinyl Panel"
    assert items[0]["unit"] == "panel"
    assert items[0]["category_name"] == "fencing"


def test_add_item_returns_404_for_unknown_material(
    db_session, make_template, make_user, make_session
):
    template = make_template()
    client = _admin_client(make_user, make_session)

    response = client.post(
        f"/project-templates/{template.id}/items",
        json={"material_id": str(uuid.uuid4())},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_add_item_returns_404_for_unknown_template(
    db_session, make_material, make_user, make_session
):
    material = make_material()
    client = _admin_client(make_user, make_session)

    response = client.post(
        f"/project-templates/{uuid.uuid4()}/items",
        json={"material_id": str(material.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_add_same_material_twice_returns_201_and_creates_second_row(
    db_session, make_template, make_material, make_user, make_session
):
    """ADR-0038: duplicate materials in a template are allowed — no longer
    a 409, and both rows persist as independent ProjectTemplateItem
    records for the UI to flag as duplicates."""
    template = make_template()
    material = make_material()
    client = _admin_client(make_user, make_session)

    first = client.post(
        f"/project-templates/{template.id}/items",
        json={"material_id": str(material.id)},
        headers={"X-CSRF-Token": CSRF},
    )
    assert first.status_code == 201

    second = client.post(
        f"/project-templates/{template.id}/items",
        json={"material_id": str(material.id)},
        headers={"X-CSRF-Token": CSRF},
    )
    assert second.status_code == 201

    session, *_ = db_session
    from app.models import ProjectTemplateItem

    count = (
        session.query(ProjectTemplateItem)
        .filter_by(template_id=template.id, material_id=material.id)
        .count()
    )
    assert count == 2


def test_rename_template_changes_name(db_session, make_template, make_user, make_session):
    template = make_template(name=f"Old Name {uuid.uuid4().hex[:8]}")
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/project-templates/{template.id}",
        json={"name": "New Name"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


def test_rename_template_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/project-templates/{uuid.uuid4()}",
        json={"name": "X"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_remove_item_from_template(
    db_session, make_template, make_material, make_user, make_session
):
    material = make_material()
    template = make_template(materials=[material])
    item_id = template.items[0].id
    client = _admin_client(make_user, make_session)

    response = client.delete(
        f"/project-templates/{template.id}/items/{item_id}",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_remove_item_returns_404_for_unknown_item(
    db_session, make_template, make_user, make_session
):
    template = make_template()
    client = _admin_client(make_user, make_session)

    response = client.delete(
        f"/project-templates/{template.id}/items/{uuid.uuid4()}",
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_delete_template_removes_it_and_its_items(
    db_session, make_template, make_material, make_user, make_session
):
    session, _material_ids, template_ids, _project_ids, _user_ids = db_session
    material = make_material()
    template = make_template(materials=[material])
    template_ids.remove(template.id)
    client = _admin_client(make_user, make_session)

    response = client.delete(
        f"/project-templates/{template.id}", headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 204

    from app.models import ProjectTemplate, ProjectTemplateItem

    assert session.get(ProjectTemplate, template.id) is None
    assert (
        session.query(ProjectTemplateItem).filter_by(template_id=template.id).count() == 0
    )


def test_delete_template_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/project-templates/{uuid.uuid4()}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 404


def test_list_templates_includes_created_template_with_items(
    db_session, make_template, make_material, make_user, make_session
):
    material = make_material(canonical_name="Listed Material")
    template = make_template(materials=[material])
    client = _admin_client(make_user, make_session)

    response = client.get("/project-templates")

    assert response.status_code == 200
    matching = [row for row in response.json() if row["id"] == str(template.id)]
    assert len(matching) == 1
    assert matching[0]["items"][0]["canonical_name"] == "Listed Material"


# --- material deletion, soft cascade ---


def test_deleting_material_removes_it_from_template_but_keeps_template(
    db_session, make_template, make_material, make_user, make_session
):
    session, material_ids, template_ids, _project_ids, _user_ids = db_session
    material_a = make_material()
    material_b = make_material()
    template = make_template(materials=[material_a, material_b])
    material_ids.remove(material_a.id)
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/materials/{material_a.id}", headers={"X-CSRF-Token": CSRF})
    assert response.status_code == 204

    from app.models import ProjectTemplate, ProjectTemplateItem

    session.expire_all()
    remaining_template = session.get(ProjectTemplate, template.id)
    assert remaining_template is not None
    remaining_items = (
        session.query(ProjectTemplateItem).filter_by(template_id=template.id).all()
    )
    assert len(remaining_items) == 1
    assert remaining_items[0].material_id == material_b.id
