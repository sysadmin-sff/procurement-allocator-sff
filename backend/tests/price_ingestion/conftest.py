import uuid
import uuid as _uuid
from datetime import datetime, timezone

import pytest

from app.auth.constants import SESSION_IDLE_TTL
from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import (
    Category,
    Material,
    Price,
    PriceListEntry,
    PriceListImport,
    Supplier,
    SupplierMaterialAlias,
    User,
    UserSession,
)


@pytest.fixture
def db_session():
    session = SessionLocal()
    material_ids: list = []
    supplier_ids: list = []
    user_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, material_ids, supplier_ids, user_ids
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
        if user_ids:
            session.query(UserSession).filter(UserSession.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            session.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        session.commit()
        session.close()


@pytest.fixture
def make_user(db_session):
    session, _material_ids, _supplier_ids, user_ids = db_session

    def _make(
        email="employee@screen-factory-florida.com",
        google_sub=None,
        role="employee",
        is_active=True,
        name="Test User",
    ):
        user = User(email=email, google_sub=google_sub, role=role, is_active=is_active, name=name)
        session.add(user)
        session.flush()
        user_ids.append(user.id)
        return user

    return _make


@pytest.fixture
def make_session(db_session):
    session, *_ = db_session

    def _make(user, csrf_token="test-csrf-token"):
        now = datetime.now(timezone.utc)
        user_session = UserSession(
            id=_uuid.uuid4(),
            user_id=user.id,
            csrf_token=csrf_token,
            created_at=now,
            expires_at=now + SESSION_IDLE_TTL,
            last_seen_at=now,
        )
        session.add(user_session)
        session.flush()
        return user_session

    return _make


@pytest.fixture
def make_supplier(db_session):
    session, _material_ids, supplier_ids, _user_ids = db_session

    def _make(name="Test Supplier"):
        supplier = Supplier(name=name, currency="USD", delivery_policy={})
        session.add(supplier)
        session.flush()
        supplier_ids.append(supplier.id)
        return supplier

    return _make


@pytest.fixture
def make_category(db_session):
    """Self-contained fixture (own cleanup list, not routed through
    db_session's shared tuple) so adding it doesn't change db_session's
    yielded shape — every other test file in this directory destructures
    db_session positionally as a 4-tuple, and changing that would break
    ~50 unrelated call sites for a fixture only price_ingestion's category
    tests need."""
    session, *_ = db_session
    created_ids: list = []
    counter = {"n": 0}

    def _make(name=None, sku_prefix=None, requires_single_supplier=False):
        counter["n"] += 1
        name = name or f"Test Category {counter['n']}"
        sku_prefix = sku_prefix or f"TC{counter['n']}"
        category = Category(
            name=name, sku_prefix=sku_prefix, requires_single_supplier=requires_single_supplier
        )
        session.add(category)
        session.flush()
        created_ids.append(category.id)
        return category

    yield _make

    if created_ids:
        # Materials referencing these categories are deleted later, in
        # db_session's own teardown (fixture teardown is LIFO -- this runs
        # first since make_category depends on db_session). Null out the FK
        # first so this delete doesn't violate it before that cleanup runs.
        session.query(Material).filter(Material.category_id.in_(created_ids)).update(
            {"category_id": None}, synchronize_session=False
        )
        session.query(Category).filter(Category.id.in_(created_ids)).delete(
            synchronize_session=False
        )
        session.commit()


@pytest.fixture
def make_material(db_session):
    session, material_ids, _supplier_ids, _user_ids = db_session

    def _make(canonical_name=None, unit="ft", attributes=None, category=None):
        sku = f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            category_id=category.id if category is not None else None,
            unit=unit,
            attributes=attributes or {},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make
