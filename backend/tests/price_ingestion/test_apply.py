"""Tests for app.price_ingestion.apply — see ADR-0019 §5.

Covers: match applies a version-bumped Price + upserts alias; new creates
Material+Alias+Price atomically, rolling back all three on partial
failure; match on an existing active Price closes the old one.
"""

import datetime
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Material, Price, PriceListEntry, PriceListImport, SupplierMaterialAlias
from app.price_ingestion.apply import EntryNotFoundError, apply_price_list_entry


def _make_import(session, supplier):
    price_list_import = PriceListImport(
        supplier_id=supplier.id,
        file_ref="test.pdf",
        uploaded_at=datetime.datetime.now(datetime.timezone.utc),
        status="pending_review",
    )
    session.add(price_list_import)
    session.flush()
    return price_list_import


def _make_entry(session, price_list_import, **overrides):
    defaults = dict(
        import_id=price_list_import.id,
        supplier_raw_name="Raw Name",
        price=10.0,
        currency="USD",
    )
    defaults.update(overrides)
    entry = PriceListEntry(**defaults)
    session.add(entry)
    session.flush()
    return entry


def test_apply_match_creates_new_price_version_and_upserts_alias(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material = make_material()
    price_list_import = _make_import(session, supplier)
    entry = _make_entry(
        session, price_list_import, supplier_raw_name="ACME Screen", price=7.5
    )

    updated = apply_price_list_entry(
        session, price_list_import.id, entry.id, action="match", material_id=material.id
    )

    assert updated.action == "match"
    active_price = (
        session.query(Price)
        .filter(
            Price.material_id == material.id,
            Price.supplier_id == supplier.id,
            Price.valid_to.is_(None),
        )
        .one()
    )
    assert float(active_price.price) == 7.5
    assert active_price.source_import_id == price_list_import.id

    alias = (
        session.query(SupplierMaterialAlias)
        .filter_by(supplier_id=supplier.id, material_id=material.id)
        .one()
    )
    assert alias.supplier_raw_name == "ACME Screen"


def test_apply_match_closes_existing_active_price(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material = make_material()
    old_price = Price(
        material_id=material.id,
        supplier_id=supplier.id,
        price=5.0,
        currency="USD",
        valid_from=datetime.date(2026, 1, 1),
        valid_to=None,
    )
    session.add(old_price)
    session.flush()

    price_list_import = _make_import(session, supplier)
    entry = _make_entry(session, price_list_import, price=6.0)

    apply_price_list_entry(
        session, price_list_import.id, entry.id, action="match", material_id=material.id
    )

    session.refresh(old_price)
    assert old_price.valid_to is not None

    active_prices = (
        session.query(Price)
        .filter(
            Price.material_id == material.id,
            Price.supplier_id == supplier.id,
            Price.valid_to.is_(None),
        )
        .all()
    )
    assert len(active_prices) == 1
    assert float(active_prices[0].price) == 6.0


def test_apply_match_does_not_duplicate_existing_alias(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material = make_material()
    session.add(
        SupplierMaterialAlias(
            supplier_id=supplier.id,
            material_id=material.id,
            supplier_raw_name="Existing Alias Name",
        )
    )
    session.commit()

    price_list_import = _make_import(session, supplier)
    entry = _make_entry(
        session, price_list_import, supplier_raw_name="Existing Alias Name"
    )

    apply_price_list_entry(
        session, price_list_import.id, entry.id, action="match", material_id=material.id
    )

    aliases = (
        session.query(SupplierMaterialAlias)
        .filter_by(supplier_id=supplier.id, material_id=material.id)
        .all()
    )
    assert len(aliases) == 1


def test_apply_new_creates_material_alias_and_price_atomically(
    db_session, make_supplier
):
    session, material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    price_list_import = _make_import(session, supplier)
    entry = _make_entry(
        session, price_list_import, supplier_raw_name="Brand New Screen", price=12.0
    )

    with patch("app.price_ingestion.apply.embed_text", return_value=[0.1] * 1536):
        updated = apply_price_list_entry(
            session,
            price_list_import.id,
            entry.id,
            action="new",
            internal_sku="NEW-SKU-100",
            canonical_name="Brand New Screen",
        )

    assert updated.action == "new"
    material = session.query(Material).filter_by(internal_sku="NEW-SKU-100").one()
    # created by apply.py, not make_material() — register for teardown
    material_ids.append(material.id)
    assert material.embedding is not None

    alias = session.query(SupplierMaterialAlias).filter_by(material_id=material.id).one()
    assert alias.supplier_raw_name == "Brand New Screen"

    price = session.query(Price).filter_by(material_id=material.id).one()
    assert float(price.price) == 12.0


def test_apply_new_rolls_back_material_when_price_creation_fails(
    db_session, make_supplier
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    price_list_import = _make_import(session, supplier)
    entry = _make_entry(
        session, price_list_import, supplier_raw_name="Will Fail", price=9.0
    )

    with patch("app.price_ingestion.apply.embed_text", return_value=[0.1] * 1536):
        with patch(
            "app.price_ingestion.apply.Price",
            side_effect=IntegrityError("boom", None, Exception("boom")),
        ):
            with pytest.raises(IntegrityError):
                apply_price_list_entry(
                    session,
                    price_list_import.id,
                    entry.id,
                    action="new",
                    internal_sku="ROLLBACK-SKU",
                    canonical_name="Will Fail",
                )

    session.rollback()
    assert session.query(Material).filter_by(internal_sku="ROLLBACK-SKU").first() is None


def test_apply_raises_entry_not_found_for_unknown_entry(db_session, make_supplier):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    price_list_import = _make_import(session, supplier)

    with pytest.raises(EntryNotFoundError):
        apply_price_list_entry(
            session, price_list_import.id, uuid.uuid4(), action="match", material_id=uuid.uuid4()
        )
