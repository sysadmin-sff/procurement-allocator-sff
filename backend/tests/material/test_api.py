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


def test_create_material_returns_201_with_body(db_session, make_user, make_session, make_category):
    session, material_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)
    category = make_category(name="Fencing", sku_prefix="FENC")

    response = client.post(
        "/materials",
        json={
            "canonical_name": "6ft Vinyl Fence Panel",
            "category_id": str(category.id),
            "unit": "panel",
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))
    assert body["canonical_name"] == "6ft Vinyl Fence Panel"
    assert body["category_name"] == "Fencing"
    assert body["internal_sku"] == "FENC-001"
    assert body["attributes"] == {}


def test_create_material_without_category_id_returns_422(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/materials",
        json={"canonical_name": "No Category Material", "unit": "ft"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_create_material_ignores_internal_sku_in_payload_returns_422(
    make_user, make_session, make_category
):
    """ADR-0034 п.7 explicit choice: internal_sku is not accepted at all --
    Pydantic's default extra="ignore" would silently drop it, but this
    project chooses to make the removal visible via strict rejection. See
    MaterialCreate's model_config in schemas/material.py."""
    client = _admin_client(make_user, make_session)
    category = make_category()

    response = client.post(
        "/materials",
        json={
            "canonical_name": "Explicit SKU Attempt",
            "category_id": str(category.id),
            "unit": "ft",
            "internal_sku": "HACKED-001",
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_create_material_generates_sku_from_category_prefix(
    db_session, make_user, make_session, make_category
):
    session, material_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)
    category = make_category(name="TestDoors", sku_prefix="TDOR")

    response = client.post(
        "/materials",
        json={"canonical_name": "Door One", "category_id": str(category.id), "unit": "ea"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))
    assert body["internal_sku"] == "TDOR-001"


def test_create_material_after_backfill_continues_existing_sku_sequence(
    db_session, make_user, make_session, make_category, make_material
):
    """ADR-0034 п.4, the exact numeric regression: a Category left at
    next_sku_number=27 (as backfill would set for a 26-material Doors
    category) must produce the next SKU number, not reuse the last
    occupied number or skip one (off-by-one)."""
    session, material_ids, _user_ids = db_session
    category = make_category(name="TestDoors2", sku_prefix="TDR2", next_sku_number=27)
    make_material(sku="TDR2-026", category=category)
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/materials",
        json={
            "canonical_name": "Door Twenty Seven",
            "category_id": str(category.id),
            "unit": "ea",
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))
    assert body["internal_sku"] == "TDR2-027"


def test_create_material_sequential_calls_produce_distinct_skus_no_collision(
    db_session, make_user, make_session, make_category
):
    """ADR-0034 п.4: concurrent creation must not collide. TestClient/SQLite-
    style in-process testing can't easily exercise true DB-level concurrent
    transactions, so this test uses two sequential creates against the same
    Category row to prove the atomic UPDATE ... RETURNING counter advances
    correctly and never repeats a number."""
    session, material_ids, _user_ids = db_session
    category = make_category(name="RaceCat", sku_prefix="RACE")
    client = _admin_client(make_user, make_session)

    first = client.post(
        "/materials",
        json={"canonical_name": "Race One", "category_id": str(category.id), "unit": "ea"},
        headers={"X-CSRF-Token": CSRF},
    )
    second = client.post(
        "/materials",
        json={"canonical_name": "Race Two", "category_id": str(category.id), "unit": "ea"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    material_ids.append(uuid.UUID(first.json()["id"]))
    material_ids.append(uuid.UUID(second.json()["id"]))
    assert first.json()["internal_sku"] != second.json()["internal_sku"]
    assert {first.json()["internal_sku"], second.json()["internal_sku"]} == {
        "RACE-001",
        "RACE-002",
    }


def test_get_material_returns_created_material(
    db_session, make_material, make_user, make_session
):
    material = make_material(canonical_name="Get Me Material")
    client = _admin_client(make_user, make_session)

    response = client.get(f"/materials/{material.id}")

    assert response.status_code == 200
    assert response.json()["canonical_name"] == "Get Me Material"


def test_get_material_includes_color_options_and_fragment(
    db_session, make_material, make_user, make_session
):
    """Regression: MaterialOut omitted color_options/color_fragment entirely,
    so every material endpoint silently dropped them from the response even
    though the DB had them set — resolveMaterialName/resolve_material_name
    on the frontend always saw color_options as absent and fell back to the
    unresolved "(White/Bronze)" canonical_name. See ADR-0031."""
    session, _material_ids, _user_ids = db_session
    material = make_material(canonical_name="7 Super Gutter x 24' (White/Bronze)")
    material.color_options = ["White", "Bronze"]
    material.color_fragment = "(White/Bronze)"
    session.commit()
    client = _admin_client(make_user, make_session)

    response = client.get(f"/materials/{material.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["color_options"] == ["White", "Bronze"]
    assert body["color_fragment"] == "(White/Bronze)"


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
        json={"canonical_name": "New Name", "unit": "ft"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["canonical_name"] == "New Name"


def test_update_material_cannot_set_internal_sku(
    db_session, make_material, make_user, make_session
):
    material = make_material()
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/materials/{material.id}",
        json={"canonical_name": "Renamed", "internal_sku": "SHOULD-NOT-APPLY"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_update_material_can_reclassify_category_without_new_sku(
    db_session, make_material, make_category, make_user, make_session
):
    """ADR-0034 п.4: PATCH may change category_id (reclassification) but
    never touches internal_sku -- the SKU issued at creation persists
    regardless of later recategorization."""
    old_category = make_category(name="Old", sku_prefix="OLD")
    new_category = make_category(name="New", sku_prefix="NEW")
    material = make_material(sku="OLD-001", category=old_category)
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/materials/{material.id}",
        json={"category_id": str(new_category.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["internal_sku"] == "OLD-001"
    assert body["category_name"] == "New"


def test_update_material_partial_payload_preserves_omitted_fields(
    db_session, make_material, make_category, make_user, make_session
):
    fencing = make_category(name="fencing")
    material = make_material(
        canonical_name="Kept Name", category=fencing, unit="panel", attributes={"gauge": "6"}
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
    assert body["category_name"] == "fencing"
    assert body["unit"] == "panel"
    assert body["attributes"] == {"gauge": "6"}


def test_update_material_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/materials/{uuid.uuid4()}",
        json={"canonical_name": "X", "unit": "ft"},
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


def test_search_materials_escapes_ilike_wildcards_in_query(
    db_session, make_material, make_user, make_session
):
    """% and _ are ILIKE wildcards — a query containing them literally must
    not be treated as a wildcard pattern. Regression for
    docs/known-issues.md 'search_materials не экранирует %/_'."""
    make_material(canonical_name="100% Cotton Mesh")
    # would match unescaped "100%" (% = any chars)
    make_material(canonical_name="10025 Cotton Mesh")
    make_material(canonical_name="Foo_Bar Bracket")
    # would match unescaped "Foo_Bar" (_ = any char)
    make_material(canonical_name="FooXBar Bracket")
    client = _admin_client(make_user, make_session)

    percent_response = client.get("/materials/search", params={"q": "100%"})
    assert percent_response.status_code == 200
    percent_names = [row["canonical_name"] for row in percent_response.json()]
    assert percent_names == ["100% Cotton Mesh"]

    underscore_response = client.get("/materials/search", params={"q": "Foo_Bar"})
    assert underscore_response.status_code == 200
    underscore_names = [row["canonical_name"] for row in underscore_response.json()]
    assert underscore_names == ["Foo_Bar Bracket"]


def test_search_materials_requires_minimum_query_length(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.get("/materials/search", params={"q": "a"})

    assert response.status_code == 422


def test_search_materials_returns_empty_list_for_no_matches(db_session, make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.get("/materials/search", params={"q": "zzz-no-match-zzz"})

    assert response.status_code == 200
    assert response.json() == []


def test_create_material_embeds_synchronously(db_session, make_user, make_session, make_category):
    session, material_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)
    category = make_category()

    with patch(
        "app.api.material.embed_text", return_value=[0.2] * 1536
    ) as mock_embed:
        response = client.post(
            "/materials",
            json={
                "canonical_name": "Embeddable Material",
                "category_id": str(category.id),
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


def test_create_material_survives_embedding_api_failure(
    db_session, make_user, make_session, make_category
):
    from app.price_ingestion.embeddings import EmbeddingError

    session, material_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)
    category = make_category()

    with patch(
        "app.api.material.embed_text", side_effect=EmbeddingError("boom")
    ):
        response = client.post(
            "/materials",
            json={
                "canonical_name": "Should Still Be Created",
                "category_id": str(category.id),
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
    db_session, make_material, make_category, make_user, make_session
):
    material = make_material(canonical_name="Stable Name")
    other_category = make_category(name="new-category")
    client = _admin_client(make_user, make_session)

    with patch("app.api.material.embed_text") as mock_embed:
        response = client.put(
            f"/materials/{material.id}",
            json={"category_id": str(other_category.id)},
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
