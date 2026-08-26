import uuid
from unittest.mock import patch

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
    email = f"admin-material{_admin_email_counter[0]}@screen-factory-florida.com"
    admin = make_user(email=email, role="admin")
    admin_session = make_session(admin, csrf_token=CSRF)
    return _client_as(admin_session)


def test_create_material_returns_201_with_body(db_session, make_user, make_session):
    session, material_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/materials",
        json={
            "internal_sku": f"SKU-{uuid.uuid4().hex[:8]}",
            "canonical_name": "6ft Vinyl Fence Panel",
            "category": "fencing",
            "unit": "panel",
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))
    assert body["canonical_name"] == "6ft Vinyl Fence Panel"
    assert body["category"] == "fencing"
    assert body["attributes"] == {}


def test_create_material_returns_409_for_duplicate_sku(
    db_session, make_material, make_user, make_session
):
    material = make_material()
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/materials",
        json={
            "internal_sku": material.internal_sku,
            "canonical_name": "Different Name",
            "unit": "ft",
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409


def test_get_material_returns_created_material(
    db_session, make_material, make_user, make_session
):
    material = make_material(canonical_name="Get Me Material")
    client = _admin_client(make_user, make_session)

    response = client.get(f"/materials/{material.id}")

    assert response.status_code == 200
    assert response.json()["canonical_name"] == "Get Me Material"


def test_get_material_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.get(f"/materials/{uuid.uuid4()}")

    assert response.status_code == 404


def test_list_materials_includes_created_materials(
    db_session, make_material, make_user, make_session
):
    material = make_material(canonical_name="Listed Material")
    client = _admin_client(make_user, make_session)

    response = client.get("/materials")

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert str(material.id) in ids


def test_update_material_changes_fields(db_session, make_material, make_user, make_session):
    material = make_material(canonical_name="Old Name")
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/materials/{material.id}",
        json={
            "internal_sku": material.internal_sku,
            "canonical_name": "New Name",
            "unit": "ft",
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["canonical_name"] == "New Name"


def test_update_material_returns_409_when_sku_collides(
    db_session, make_material, make_user, make_session
):
    material_a = make_material()
    material_b = make_material()
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/materials/{material_b.id}",
        json={
            "internal_sku": material_a.internal_sku,
            "canonical_name": material_b.canonical_name,
            "unit": "ft",
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409


def test_update_material_partial_payload_preserves_omitted_fields(
    db_session, make_material, make_user, make_session
):
    material = make_material(
        canonical_name="Kept Name", category="fencing", unit="panel", attributes={"gauge": "6"}
    )
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/materials/{material.id}",
        json={"canonical_name": "Renamed Only"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["canonical_name"] == "Renamed Only"
    assert body["internal_sku"] == material.internal_sku
    assert body["category"] == "fencing"
    assert body["unit"] == "panel"
    assert body["attributes"] == {"gauge": "6"}


def test_update_material_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/materials/{uuid.uuid4()}",
        json={"internal_sku": "X", "canonical_name": "X", "unit": "ft"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_delete_material_removes_it(db_session, make_material, make_user, make_session):
    session, material_ids, _user_ids = db_session
    material = make_material()
    material_ids.remove(material.id)
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/materials/{material.id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 204
    assert client.get(f"/materials/{material.id}").status_code == 404


def test_delete_material_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/materials/{uuid.uuid4()}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 404


def test_delete_material_returns_409_when_referenced_by_price(
    db_session, make_material, make_user, make_session
):
    import datetime

    from app.models import Price, Supplier

    session, material_ids, _user_ids = db_session
    material = make_material()
    supplier = Supplier(name="Ref Supplier", currency="USD", delivery_policy={})
    session.add(supplier)
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

    response = client.delete(f"/materials/{material.id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 409

    session.delete(price)
    session.delete(supplier)
    session.commit()


def test_search_materials_matches_partial_canonical_name(
    db_session, make_material, make_user, make_session
):
    make_material(canonical_name="6ft Vinyl Fence Panel")
    make_material(canonical_name="Aluminum Gate Hinge")
    client = _admin_client(make_user, make_session)

    response = client.get("/materials/search", params={"q": "vinyl"})

    assert response.status_code == 200
    names = [row["canonical_name"] for row in response.json()]
    assert "6ft Vinyl Fence Panel" in names
    assert "Aluminum Gate Hinge" not in names


def test_search_materials_requires_minimum_query_length(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.get("/materials/search", params={"q": "a"})

    assert response.status_code == 422


def test_search_materials_returns_empty_list_for_no_matches(db_session, make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.get("/materials/search", params={"q": "zzz-no-match-zzz"})

    assert response.status_code == 200
    assert response.json() == []


def test_create_material_embeds_synchronously(db_session, make_user, make_session):
    session, material_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)

    with patch(
        "app.api.material.embed_text", return_value=[0.2] * 1536
    ) as mock_embed:
        response = client.post(
            "/materials",
            json={
                "internal_sku": f"SKU-{uuid.uuid4().hex[:8]}",
                "canonical_name": "Embeddable Material",
                "unit": "ft",
            },
            headers={"X-CSRF-Token": CSRF},
        )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))
    mock_embed.assert_called_once()

    material_cls = __import__("app.models", fromlist=["Material"]).Material
    material = session.get(material_cls, uuid.UUID(body["id"]))
    assert material.embedding is not None
    assert len(material.embedding) == 1536


def test_create_material_survives_embedding_api_failure(db_session, make_user, make_session):
    from app.price_ingestion.embeddings import EmbeddingError

    session, material_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)

    with patch(
        "app.api.material.embed_text", side_effect=EmbeddingError("boom")
    ):
        response = client.post(
            "/materials",
            json={
                "internal_sku": f"SKU-{uuid.uuid4().hex[:8]}",
                "canonical_name": "Should Still Be Created",
                "unit": "ft",
            },
            headers={"X-CSRF-Token": CSRF},
        )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))

    from app.models import Material

    material = session.get(Material, uuid.UUID(body["id"]))
    assert material.embedding is None


def test_update_material_reembeds_when_canonical_name_changes(
    db_session, make_material, make_user, make_session
):
    material = make_material(canonical_name="Old Name")
    client = _admin_client(make_user, make_session)

    with patch(
        "app.api.material.embed_text", return_value=[0.3] * 1536
    ) as mock_embed:
        response = client.put(
            f"/materials/{material.id}",
            json={"canonical_name": "New Name"},
            headers={"X-CSRF-Token": CSRF},
        )

    assert response.status_code == 200
    mock_embed.assert_called_once()


def test_update_material_reembeds_when_attributes_change(
    db_session, make_material, make_user, make_session
):
    material = make_material(canonical_name="Same Name", attributes={"gauge": "6"})
    client = _admin_client(make_user, make_session)

    with patch(
        "app.api.material.embed_text", return_value=[0.3] * 1536
    ) as mock_embed:
        response = client.put(
            f"/materials/{material.id}",
            json={"attributes": {"gauge": "8"}},
            headers={"X-CSRF-Token": CSRF},
        )

    assert response.status_code == 200
    mock_embed.assert_called_once()


def test_update_material_does_not_reembed_when_only_category_changes(
    db_session, make_material, make_user, make_session
):
    material = make_material(canonical_name="Stable Name")
    client = _admin_client(make_user, make_session)

    with patch("app.api.material.embed_text") as mock_embed:
        response = client.put(
            f"/materials/{material.id}",
            json={"category": "new-category"},
            headers={"X-CSRF-Token": CSRF},
        )

    assert response.status_code == 200
    mock_embed.assert_not_called()


def test_update_material_keeps_old_embedding_on_reembed_failure(
    db_session, make_material, make_user, make_session
):
    from app.price_ingestion.embeddings import EmbeddingError

    session, material_ids, _user_ids = db_session
    material = make_material(canonical_name="Old Name")
    material.embedding = [0.5] * 1536
    session.commit()
    client = _admin_client(make_user, make_session)

    with patch("app.api.material.embed_text", side_effect=EmbeddingError("boom")):
        response = client.put(
            f"/materials/{material.id}",
            json={"canonical_name": "New Name Triggers Reembed Attempt"},
            headers={"X-CSRF-Token": CSRF},
        )

    assert response.status_code == 200
    session.refresh(material)
    assert material.embedding == [0.5] * 1536


def test_list_materials_no_session_returns_401():
    client = TestClient(app)
    response = client.get("/materials")
    assert response.status_code == 401


def test_list_materials_as_employee_returns_403(make_user, make_session):
    employee = make_user(role="employee")
    employee_session = make_session(employee)
    response = _client_as(employee_session).get("/materials")
    assert response.status_code == 403


def test_list_materials_as_admin_succeeds(make_user, make_session):
    admin = make_user(email="admin-material-list@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin)
    response = _client_as(admin_session).get("/materials")
    assert response.status_code == 200
