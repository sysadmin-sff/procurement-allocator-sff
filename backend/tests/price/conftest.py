import datetime
import uuid

import pytest

from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import Material, Price, Supplier


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
        if material_ids:
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
def make_material(db_session):
    session, material_ids, _supplier_ids = db_session

    def _make(sku=None, unit="ft"):
        sku = sku or f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        material = Material(
            internal_sku=sku, canonical_name=sku, unit=unit, attributes={}
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make


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
def make_price(db_session):
    session, *_ = db_session

    def _make(
        material,
        supplier,
        price=10.0,
        availability=100,
        min_order_qty=1,
        valid_from=None,
        valid_to=None,
    ):
        p = Price(
            material=material,
            supplier=supplier,
            price=price,
            currency="USD",
            availability=availability,
            min_order_qty=min_order_qty,
            valid_from=valid_from or datetime.date.today(),
            valid_to=valid_to,
        )
        session.add(p)
        session.flush()
        return p

    return _make
