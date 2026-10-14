import datetime
import uuid
from datetime import timezone

import pytest

from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import Category, Material, Price, PriceListImport, Supplier

_category_ids_pending_cleanup: list = []
"""Same pattern as tests/price/conftest.py -- make_category's own teardown
can't delete Category rows yet (Material rows referencing them aren't gone
until db_session's teardown, which runs AFTER make_category's, since pytest
fixture teardown is LIFO). db_session's teardown does the actual delete
once materials/prices are cleaned up."""


@pytest.fixture
def db_session():
    global _category_ids_pending_cleanup
    _category_ids_pending_cleanup = []
    session = SessionLocal()
    material_ids: list = []
    supplier_ids: list = []
    price_list_import_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, material_ids, supplier_ids, price_list_import_ids
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
        if price_list_import_ids:
            session.query(PriceListImport).filter(
                PriceListImport.id.in_(price_list_import_ids)
            ).delete(synchronize_session=False)
        if _category_ids_pending_cleanup:
            session.query(Category).filter(
                Category.id.in_(_category_ids_pending_cleanup)
            ).delete(synchronize_session=False)
        session.commit()
        session.close()


@pytest.fixture
def make_category(db_session):
    session, *_ = db_session
    created_ids: list = []
    counter = {"n": 0}

    def _make(name=None, sku_prefix=None):
        counter["n"] += 1
        name = name or f"MOQ Audit Test Category {uuid.uuid4().hex[:12]}"
        sku_prefix = sku_prefix or f"TC{uuid.uuid4().hex[:6].upper()}"
        category = Category(
            name=name,
            sku_prefix=sku_prefix,
            requires_single_supplier=False,
            next_sku_number=1,
            display_order=10_000 + counter["n"],
        )
        session.add(category)
        session.flush()
        created_ids.append(category.id)
        return category

    yield _make

    if created_ids:
        _category_ids_pending_cleanup.extend(created_ids)


@pytest.fixture
def make_material(db_session, make_category):
    session, material_ids, _supplier_ids, _price_list_import_ids = db_session

    def _make(sku=None, canonical_name=None, category=None, unit="pcs"):
        sku = sku or f"MOQ-TEST-SKU-{uuid.uuid4().hex[:12]}"
        if category is None:
            category = make_category()
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            category_id=category.id,
            unit=unit,
            attributes={},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make


@pytest.fixture
def make_supplier(db_session):
    session, _material_ids, supplier_ids, _price_list_import_ids = db_session

    def _make(name=None, is_active_for_allocation=True):
        name = name or f"MOQ Audit Test Supplier {uuid.uuid4().hex[:12]}"
        supplier = Supplier(
            name=name,
            currency="USD",
            delivery_policy={},
            is_active_for_allocation=is_active_for_allocation,
        )
        session.add(supplier)
        session.flush()
        supplier_ids.append(supplier.id)
        return supplier

    return _make


@pytest.fixture
def make_price_list_import(db_session, make_supplier):
    session, _material_ids, _supplier_ids, price_list_import_ids = db_session

    def _make(supplier=None):
        supplier = supplier or make_supplier()
        price_list_import = PriceListImport(
            supplier_id=supplier.id,
            file_ref="moq-audit-test-fixture.pdf",
            uploaded_at=datetime.datetime.now(timezone.utc),
            status="approved",
        )
        session.add(price_list_import)
        session.flush()
        price_list_import_ids.append(price_list_import.id)
        return price_list_import

    return _make


@pytest.fixture
def make_price(db_session):
    session, *_ = db_session

    def _make(
        material,
        supplier,
        price=10.0,
        availability=None,
        min_order_qty=None,
        valid_from=None,
        valid_to=None,
        source_import_id=None,
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
            source_import_id=source_import_id,
        )
        session.add(p)
        session.flush()
        return p

    return _make
