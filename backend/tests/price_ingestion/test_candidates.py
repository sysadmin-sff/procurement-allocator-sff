"""Tests for app.price_ingestion.candidates — see ADR-0019 §2/§3.

Requires a real Postgres with pgvector (same DB as the rest of the test
suite) since these tests exercise the actual <=> operator and DB
constraints, not mocks.
"""

from app.models import SupplierMaterialAlias
from app.price_ingestion.candidates import find_known_alias, find_top_candidates


def test_find_known_alias_returns_exact_match(db_session, make_supplier, make_material):
    session, _material_ids, supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material = make_material()
    alias = SupplierMaterialAlias(
        supplier_id=supplier.id,
        material_id=material.id,
        supplier_raw_name="ACME Fiberglass 18x14",
    )
    session.add(alias)
    session.commit()

    found = find_known_alias(session, supplier.id, "ACME Fiberglass 18x14")

    assert found is not None
    assert found.material_id == material.id


def test_find_known_alias_returns_none_when_no_match(db_session, make_supplier):
    session, _material_ids, supplier_ids, _user_ids = db_session
    supplier = make_supplier()

    found = find_known_alias(session, supplier.id, "Never Seen Before")

    assert found is None


def test_find_known_alias_is_scoped_to_supplier(db_session, make_supplier, make_material):
    session, _material_ids, supplier_ids, _user_ids = db_session
    supplier_a = make_supplier(name="Supplier A")
    supplier_b = make_supplier(name="Supplier B")
    material = make_material()
    session.add(
        SupplierMaterialAlias(
            supplier_id=supplier_a.id,
            material_id=material.id,
            supplier_raw_name="Shared Raw Name",
        )
    )
    session.commit()

    found = find_known_alias(session, supplier_b.id, "Shared Raw Name")

    assert found is None


def test_find_top_candidates_orders_by_cosine_distance(db_session, make_material):
    # Note: this dev DB is pre-seeded with ~300 real Material rows that
    # already have embeddings (from prior backfill work), so a small k
    # would let unrelated seed rows crowd "far" out of the slice before
    # we ever get to compare its position against "close". Use a k large
    # enough to guarantee both synthetic points are present regardless of
    # table size, so the assertion is actually testing ordering, not
    # table contents.
    session, _material_ids, _supplier_ids, _user_ids = db_session
    close = make_material(canonical_name="Close Match")
    close.embedding = [1.0] + [0.0] * 1535
    far = make_material(canonical_name="Far Match")
    far.embedding = [0.0, 1.0] + [0.0] * 1534
    session.commit()

    query_vector = [0.99] + [0.01] * 1535
    results = find_top_candidates(session, query_vector, k=1000)

    result_ids = [m.id for m in results]
    assert close.id in result_ids
    assert far.id in result_ids
    assert result_ids.index(close.id) < result_ids.index(far.id)


def test_find_top_candidates_excludes_null_embedding(db_session, make_material):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    no_embedding = make_material(canonical_name="No Embedding")
    assert no_embedding.embedding is None

    query_vector = [0.5] * 1536
    results = find_top_candidates(session, query_vector, k=5)

    assert no_embedding.id not in [m.id for m in results]


def test_find_top_candidates_respects_k_limit(db_session, make_material):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    for i in range(7):
        m = make_material(canonical_name=f"Material {i}")
        m.embedding = [float(i)] + [0.0] * 1535
    session.commit()

    results = find_top_candidates(session, [0.0] * 1536, k=5)

    assert len(results) == 5
