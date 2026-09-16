import uuid
import uuid as _uuid
from datetime import datetime, timezone

import pytest

from app.auth.constants import SESSION_IDLE_TTL
from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import Category, Material, User, UserSession

_category_ids_pending_cleanup: list = []
"""Populated by make_category's own teardown when a Category delete can't
run yet (its materials aren't gone until db_session's teardown, which runs
AFTER make_category's -- pytest fixture teardown is LIFO, and make_category
depends on db_session). db_session's own teardown does the actual delete
once materials are cleaned up. Module-level and cleared at the start of each
db_session run so state never leaks between tests."""


@pytest.fixture
def db_session():
    global _category_ids_pending_cleanup
    _category_ids_pending_cleanup = []
    session = SessionLocal()
    material_ids: list = []
    user_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, material_ids, user_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
        if material_ids:
            session.query(Material).filter(Material.id.in_(material_ids)).delete(
                synchronize_session=False
            )
        if user_ids:
            session.query(UserSession).filter(UserSession.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            session.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        if _category_ids_pending_cleanup:
            # Materials referencing these are gone now (deleted just above),
            # so the Category delete that make_category's own teardown
            # couldn't complete (LIFO teardown order — see module docstring)
            # can run here instead.
            session.query(Category).filter(
                Category.id.in_(_category_ids_pending_cleanup)
            ).delete(synchronize_session=False)
        session.commit()
        session.close()


@pytest.fixture
def make_user(db_session):
    session, _material_ids, user_ids = db_session

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
def make_category(db_session):
    """Self-contained fixture (own cleanup list, not routed through
    db_session's shared tuple) so adding it doesn't change db_session's
    yielded shape — several call sites in this directory destructure
    db_session positionally with a fixed arity."""
    session, *_ = db_session
    created_ids: list = []
    counter = {"n": 0}

    def _make(name=None, sku_prefix=None, requires_single_supplier=False, next_sku_number=1):
        counter["n"] += 1
        name = name or f"Test Category {uuid.uuid4().hex[:12]}"
        sku_prefix = sku_prefix or f"TC{uuid.uuid4().hex[:6].upper()}"
        category = Category(
            name=name,
            sku_prefix=sku_prefix,
            requires_single_supplier=requires_single_supplier,
            next_sku_number=next_sku_number,
        )
        session.add(category)
        session.flush()
        created_ids.append(category.id)
        return category

    yield _make

    if created_ids:
        # Can't delete these Category rows yet -- any Material created
        # against them (by make_material or directly) is still referenced by
        # db_session's own material_ids list, and possibly by Price/other
        # rows db_session's teardown hasn't cleaned up yet either. This
        # fixture's teardown runs BEFORE db_session's (pytest fixture
        # teardown is LIFO, and make_category depends on db_session), so
        # hand the ids off to be deleted there instead, once cleanup order
        # is actually safe.
        _category_ids_pending_cleanup.extend(created_ids)


@pytest.fixture
def make_material(db_session, make_category):
    session, material_ids, _user_ids = db_session

    def _make(sku=None, canonical_name=None, category=None, unit="ft", attributes=None):
        sku = sku or f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        if category is None:
            category = make_category()
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            category_id=category.id,
            unit=unit,
            attributes=attributes or {},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make
