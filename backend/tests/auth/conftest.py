import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.constants import SESSION_IDLE_TTL
from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import User, UserSession


@pytest.fixture
def db_session():
    session = SessionLocal()
    user_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, user_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
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

    def _make(
        email="employee@screen-factory-florida.com",
        google_sub=None,
        role="employee",
        is_active=True,
        name="Test User",
    ):
        user = User(
            email=email,
            google_sub=google_sub,
            role=role,
            is_active=is_active,
            name=name,
        )
        session.add(user)
        session.flush()
        user_ids.append(user.id)
        return user

    return _make


@pytest.fixture
def make_session(db_session):
    session, _ = db_session

    def _make(user, csrf_token="test-csrf-token", expired=False, absolute_expired=False):
        now = datetime.now(timezone.utc)
        created_at = now - timedelta(days=31) if absolute_expired else now
        expires_at = now - timedelta(hours=1) if expired else now + SESSION_IDLE_TTL
        user_session = UserSession(
            id=uuid.uuid4(),
            user_id=user.id,
            csrf_token=csrf_token,
            created_at=created_at,
            expires_at=expires_at,
            last_seen_at=now,
        )
        session.add(user_session)
        session.flush()
        return user_session

    return _make
