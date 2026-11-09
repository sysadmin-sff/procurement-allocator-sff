import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth.constants import SESSION_IDLE_TTL
from app.core.database import SessionLocal, get_db
from app.measurements.models import (
    MeasurementsAmoEvent,
    MeasurementsLead,
    MeasurementsSyncState,
    MeasurementsUserAccess,
    MeasurementsVisit,
)
from app.models import User, UserSession
from tests.measurements.helpers import load_app


@pytest.fixture
def db_session():
    """`get_current_user` commits, so rows are removed explicitly at teardown."""
    session = SessionLocal()
    user_ids: list = []
    try:
        yield session, user_ids
    finally:
        session.rollback()
        for model in (
            MeasurementsVisit,
            MeasurementsLead,
            MeasurementsAmoEvent,
            MeasurementsSyncState,
            MeasurementsUserAccess,
        ):
            session.query(model).delete(synchronize_session=False)
        if user_ids:
            session.query(UserSession).filter(UserSession.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            session.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        session.commit()
        session.close()


@pytest.fixture
def make_user(db_session):
    session, user_ids = db_session

    def _make(role="employee", is_active=True, granted=False):
        user = User(
            email=f"{uuid.uuid4()}@screen-factory-florida.com",
            role=role,
            is_active=is_active,
        )
        session.add(user)
        session.flush()
        user_ids.append(user.id)
        if granted:
            session.add(MeasurementsUserAccess(user_id=user.id))
            session.flush()
        return user

    return _make


@pytest.fixture
def make_session(db_session):
    session, _ = db_session

    def _make(user):
        now = datetime.now(timezone.utc)
        user_session = UserSession(
            id=uuid.uuid4(),
            user_id=user.id,
            csrf_token="test-csrf-token",
            created_at=now,
            expires_at=now + SESSION_IDLE_TTL,
            last_seen_at=now - timedelta(minutes=1),
        )
        session.add(user_session)
        session.flush()
        return user_session

    return _make


@pytest.fixture
def enabled_app(db_session):
    session, _ = db_session
    app = load_app(enabled=True)

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    return app


@pytest.fixture
def client(enabled_app):
    return TestClient(enabled_app)
