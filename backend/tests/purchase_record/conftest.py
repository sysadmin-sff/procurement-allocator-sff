import datetime
import uuid
import uuid as _uuid
from datetime import timezone

import pytest

from app.auth.constants import SESSION_IDLE_TTL
from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import (
    AllocationLine,
    AllocationRun,
    Material,
    Order,
    OrderItem,
    Price,
    Project,
    ProjectItem,
    PurchaseRecord,
    Supplier,
    User,
    UserSession,
)


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
            session.query(PurchaseRecord).filter_by(project_id=project_id).delete(
                synchronize_session=False
            )
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
            run_ids = [
                r.id for r in session.query(AllocationRun).filter_by(project_id=project_id).all()
            ]
            if run_ids:
                session.query(AllocationLine).filter(
                    AllocationLine.allocation_run_id.in_(run_ids)
                ).delete(synchronize_session=False)
                session.query(AllocationRun).filter(AllocationRun.id.in_(run_ids)).delete(
                    synchronize_session=False
                )
            session.query(ProjectItem).filter_by(project_id=project_id).delete(
                synchronize_session=False
            )
            session.query(Project).filter_by(id=project_id).delete(synchronize_session=False)
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
        now = datetime.datetime.now(timezone.utc)
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
    session, _project_ids, _material_ids, supplier_ids, _user_ids = db_session

    def _make(
        name="Test Supplier",
        flat_fee=0.0,
        free_shipping_threshold=0.0,
        per_order_min_amount=0.0,
    ):
        supplier = Supplier(
            name=name,
            currency="USD",
            delivery_policy={
                "flat_fee": flat_fee,
                "free_shipping_threshold": free_shipping_threshold,
                "per_order_min_amount": per_order_min_amount,
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
    session, _project_ids, material_ids, _supplier_ids, _user_ids = db_session
    counter = {"n": 0}

    def _make(sku=None, unit="ft"):
        counter["n"] += 1
        sku = sku or f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        material = Material(
            internal_sku=sku,
            canonical_name=sku,
            unit=unit,
            attributes={},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make


@pytest.fixture
def make_price(db_session):
    session, *_ = db_session

    def _make(material, supplier, price, availability=100, min_order_qty=1):
        p = Price(
            material=material,
            supplier=supplier,
            price=price,
            currency="USD",
            availability=availability,
            min_order_qty=min_order_qty,
            valid_from=datetime.date.today(),
            valid_to=None,
        )
        session.add(p)
        session.flush()
        return p

    return _make


@pytest.fixture
def make_project(db_session):
    session, project_ids, _material_ids, _supplier_ids, _user_ids = db_session

    def _make(items):
        """items: list of (material, quantity) tuples."""
        project = Project(title="Test Project", status="draft")
        session.add(project)
        session.flush()
        project_ids.append(project.id)
        for material, quantity in items:
            session.add(
                ProjectItem(project_id=project.id, material_id=material.id, quantity=quantity)
            )
        session.flush()
        return project

    return _make
