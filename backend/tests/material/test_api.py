import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_create_material_returns_201_with_body(db_session):
    session, material_ids = db_session

    response = client.post(
        "/materials",
        json={
            "internal_sku": f"SKU-{uuid.uuid4().hex[:8]}",
            "canonical_name": "6ft Vinyl Fence Panel",
            "category": "fencing",
            "unit": "panel",
        },
    )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))
    assert body["canonical_name"] == "6ft Vinyl Fence Panel"
    assert body["category"] == "fencing"
    assert body["attributes"] == {}


def test_create_material_returns_409_for_duplicate_sku(db_session, make_material):
    material = make_material()

    response = client.post(
        "/materials",
        json={
            "internal_sku": material.internal_sku,
            "canonical_name": "Different Name",
            "unit": "ft",
        },
    )

    assert response.status_code == 409


def test_get_material_returns_created_material(db_session, make_material):
    material = make_material(canonical_name="Get Me Material")

    response = client.get(f"/materials/{material.id}")

    assert response.status_code == 200
    assert response.json()["canonical_name"] == "Get Me Material"


def test_get_material_returns_404_for_unknown_id():
    response = client.get(f"/materials/{uuid.uuid4()}")

    assert response.status_code == 404


def test_list_materials_includes_created_materials(db_session, make_material):
    material = make_material(canonical_name="Listed Material")

    response = client.get("/materials")

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert str(material.id) in ids


def test_update_material_changes_fields(db_session, make_material):
    material = make_material(canonical_name="Old Name")

    response = client.put(
        f"/materials/{material.id}",
        json={
            "internal_sku": material.internal_sku,
            "canonical_name": "New Name",
            "unit": "ft",
        },
    )

    assert response.status_code == 200
    assert response.json()["canonical_name"] == "New Name"


def test_update_material_returns_409_when_sku_collides(db_session, make_material):
    material_a = make_material()
    material_b = make_material()

    response = client.put(
        f"/materials/{material_b.id}",
        json={
            "internal_sku": material_a.internal_sku,
            "canonical_name": material_b.canonical_name,
            "unit": "ft",
        },
    )

    assert response.status_code == 409


def test_update_material_partial_payload_preserves_omitted_fields(db_session, make_material):
    material = make_material(
        canonical_name="Kept Name", category="fencing", unit="panel", attributes={"gauge": "6"}
    )

    response = client.put(
        f"/materials/{material.id}",
        json={"canonical_name": "Renamed Only"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["canonical_name"] == "Renamed Only"
    assert body["internal_sku"] == material.internal_sku
    assert body["category"] == "fencing"
    assert body["unit"] == "panel"
    assert body["attributes"] == {"gauge": "6"}


def test_update_material_returns_404_for_unknown_id():
    response = client.put(
        f"/materials/{uuid.uuid4()}",
        json={"internal_sku": "X", "canonical_name": "X", "unit": "ft"},
    )

    assert response.status_code == 404


def test_delete_material_removes_it(db_session, make_material):
    session, material_ids = db_session
    material = make_material()
    material_ids.remove(material.id)

    response = client.delete(f"/materials/{material.id}")

    assert response.status_code == 204
    assert client.get(f"/materials/{material.id}").status_code == 404


def test_delete_material_returns_404_for_unknown_id():
    response = client.delete(f"/materials/{uuid.uuid4()}")

    assert response.status_code == 404


def test_delete_material_returns_409_when_referenced_by_price(
    db_session, make_material
):
    import datetime

    from app.models import Price, Supplier

    session, material_ids = db_session
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

    response = client.delete(f"/materials/{material.id}")

    assert response.status_code == 409

    session.delete(price)
    session.delete(supplier)
    session.commit()


def test_search_materials_matches_partial_canonical_name(db_session, make_material):
    make_material(canonical_name="6ft Vinyl Fence Panel")
    make_material(canonical_name="Aluminum Gate Hinge")

    response = client.get("/materials/search", params={"q": "vinyl"})

    assert response.status_code == 200
    names = [row["canonical_name"] for row in response.json()]
    assert "6ft Vinyl Fence Panel" in names
    assert "Aluminum Gate Hinge" not in names


def test_search_materials_requires_minimum_query_length():
    response = client.get("/materials/search", params={"q": "a"})

    assert response.status_code == 422


def test_search_materials_returns_empty_list_for_no_matches(db_session):
    response = client.get("/materials/search", params={"q": "zzz-no-match-zzz"})

    assert response.status_code == 200
    assert response.json() == []
