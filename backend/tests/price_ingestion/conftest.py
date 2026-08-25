import uuid

import pytest

from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import (
    Material,
    Price,
    PriceListEntry,
    PriceListImport,
    Supplier,
    SupplierMaterialAlias,
)


@pytest.fixture
def db_session():
    session = SessionLocal()
    material_ids: list = []
    supplier_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, material_ids, supplier_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
        if supplier_ids:
            session.query(SupplierMaterialAlias).filter(
                SupplierMaterialAlias.supplier_id.in_(supplier_ids)
            ).delete(synchronize_session=False)
            import_ids = [
                i.id
                for i in session.query(PriceListImport)
                .filter(PriceListImport.supplier_id.in_(supplier_ids))
                .all()
            ]
            if import_ids:
                # Price.source_import_id references price_list_imports, so any
                # Price row created by apply_price_list_entry() (Task 8) must be
                # deleted before the import it points at, or the FK delete below fails.
                session.query(Price).filter(Price.source_import_id.in_(import_ids)).delete(
                    synchronize_session=False
                )
                session.query(PriceListEntry).filter(
                    PriceListEntry.import_id.in_(import_ids)
                ).delete(synchronize_session=False)
                session.query(PriceListImport).filter(
                    PriceListImport.id.in_(import_ids)
                ).delete(synchronize_session=False)
        if material_ids:
            session.query(SupplierMaterialAlias).filter(
                SupplierMaterialAlias.material_id.in_(material_ids)
            ).delete(synchronize_session=False)
            session.query(Price).filter(Price.material_id.in_(material_ids)).delete(
                synchronize_session=False
            )
            session.query(Material).filter(Material.id.in_(material_ids)).delete(
                synchronize_session=False
            )
        if supplier_ids:
            session.query(Price).filter(Price.supplier_id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
            session.query(Supplier).filter(Supplier.id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
        session.commit()
        session.close()


@pytest.fixture
def make_supplier(db_session):
    session, _material_ids, supplier_ids = db_session

    def _make(name="Test Supplier"):
        supplier = Supplier(name=name, currency="USD", delivery_policy={})
        session.add(supplier)
        session.flush()
        supplier_ids.append(supplier.id)
        return supplier

    return _make


@pytest.fixture
def make_material(db_session):
    session, material_ids, _supplier_ids = db_session

    def _make(canonical_name=None, unit="ft", attributes=None):
        sku = f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            unit=unit,
            attributes=attributes or {},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make
