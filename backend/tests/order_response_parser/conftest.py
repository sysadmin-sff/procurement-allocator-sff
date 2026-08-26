import uuid
import uuid as _uuid
from datetime import datetime, timezone

import pytest

from app.auth.constants import SESSION_IDLE_TTL
from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import Material, Order, OrderItem, Project, Supplier, User, UserSession


@pytest.fixture
def db_session():
    session = SessionLocal()
    project_ids: list = []
    material_ids: list = []
    supplier_ids: list = []
    user_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, project_ids, material_ids, supplier_ids, user_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
        for project_id in project_ids:
            order_ids = [
                o.id for o in session.query(Order).filter_by(project_id=project_id).all()
            ]
            if order_ids:
                session.query(OrderItem).filter(OrderItem.order_id.in_(order_ids)).delete(
                    synchronize_session=False
                )
                session.query(Order).filter(Order.id.in_(order_ids)).delete(
                    synchronize_session=False
                )
            session.query(Project).filter_by(id=project_id).delete(synchronize_session=False)
        if material_ids:
            session.query(Material).filter(Material.id.in_(material_ids)).delete(
                synchronize_session=False
            )
        if supplier_ids:
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
    session, *_rest, user_ids = db_session

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
    session, _order_ids, _material_ids, supplier_ids, _user_ids = db_session

    def _make(name="Test Supplier"):
        supplier = Supplier(
            name=name,
            currency="USD",
            delivery_policy={
                "flat_fee": 0.0,
                "free_shipping_threshold": 0.0,
                "per_order_min_amount": 0.0,
                "lead_time_days": 1,
            },
        )
        session.add(supplier)
        session.flush()
        supplier_ids.append(supplier.id)
        return supplier

    return _make


@pytest.fixture
def make_material(db_session):
    session, _order_ids, material_ids, _supplier_ids, _user_ids = db_session

    def _make(canonical_name=None, unit="ft"):
        sku = f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            unit=unit,
            attributes={},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make


@pytest.fixture
def make_order(db_session):
    session, project_ids, _material_ids, _supplier_ids, _user_ids = db_session

    def _make(supplier, items):
        """items: list of (material, quantity, quoted_price) tuples."""
        project = Project(title="Test Project", status="draft")
        session.add(project)
        session.flush()
        project_ids.append(project.id)

        order = Order(
            project_id=project.id,
            supplier_id=supplier.id,
            status="sent",
            total_amount=sum(qty * price for _m, qty, price in items),
            delivery_fee=0,
        )
        session.add(order)
        session.flush()
        for material, quantity, quoted_price in items:
            session.add(
                OrderItem(
                    order_id=order.id,
                    material_id=material.id,
                    quantity=quantity,
                    quoted_price=quoted_price,
                )
            )
        session.flush()
        session.refresh(order)
        return order

    return _make
