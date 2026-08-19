import pytest

from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import Office, Supplier, SupplierContact


@pytest.fixture
def db_session():
    session = SessionLocal()
    supplier_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, supplier_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
        if supplier_ids:
            session.query(SupplierContact).filter(
                SupplierContact.supplier_id.in_(supplier_ids)
            ).delete(synchronize_session=False)
            session.query(Office).filter(Office.supplier_id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
            session.query(Supplier).filter(Supplier.id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
        session.commit()
        session.close()


@pytest.fixture
def make_supplier(db_session):
    session, supplier_ids = db_session

    def _make(name="Test Supplier"):
        supplier = Supplier(name=name, currency="USD", delivery_policy={})
        session.add(supplier)
        session.flush()
        supplier_ids.append(supplier.id)
        return supplier

    return _make


@pytest.fixture
def make_office(db_session):
    session, _supplier_ids = db_session

    def _make(supplier, address="123 Main St", region=None):
        office = Office(supplier_id=supplier.id, address=address, region=region)
        session.add(office)
        session.flush()
        return office

    return _make
