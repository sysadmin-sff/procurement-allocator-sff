import pytest

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
        role="employee",
        is_active=True,
        google_sub=None,
    ):
        user = User(email=email, role=role, is_active=is_active, google_sub=google_sub)
        session.add(user)
        session.flush()
        user_ids.append(user.id)
        return user

    return _make


@pytest.fixture
def make_session(db_session):
    import uuid as uuid_module
    from datetime import datetime, timezone

    from app.auth.constants import SESSION_IDLE_TTL

    session, _ = db_session

    def _make(user, csrf_token="test-csrf"):
        now = datetime.now(timezone.utc)
        user_session = UserSession(
            id=uuid_module.uuid4(),
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
def auth_headers_and_cookies():
    def _for(user_session):
        return {
            "cookies": {"session_id": str(user_session.id)},
            "headers": {"X-CSRF-Token": user_session.csrf_token},
        }

    return _for
