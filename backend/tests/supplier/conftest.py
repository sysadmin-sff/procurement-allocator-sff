import pytest

from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import Supplier


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
            session.query(Supplier).filter(Supplier.id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
        session.commit()
        session.close()


@pytest.fixture
def make_supplier(db_session):
    session, supplier_ids = db_session

    def _make(
        name="Test Supplier",
        contacts=None,
        currency="USD",
        flat_fee=0.0,
        free_shipping_threshold=0.0,
        per_order_min_amount=0.0,
        lead_time_days=1,
    ):
        supplier = Supplier(
            name=name,
            contacts=contacts,
            currency=currency,
            delivery_policy={
                "flat_fee": flat_fee,
                "free_shipping_threshold": free_shipping_threshold,
                "per_order_min_amount": per_order_min_amount,
                "lead_time_days": lead_time_days,
            },
        )
        session.add(supplier)
        session.flush()
        supplier_ids.append(supplier.id)
        return supplier

    return _make
