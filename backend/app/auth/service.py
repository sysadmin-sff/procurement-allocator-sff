import uuid
from datetime import timezone

from sqlalchemy.orm import Session

from app.auth.constants import SESSION_ABSOLUTE_TTL, SESSION_IDLE_TTL
from app.auth.cookies import utcnow
from app.auth.google import GoogleClaims
from app.models import User, UserSession


class LoginRejectedError(Exception):
    """Carries the true rejection reason for internal logging only. Callers
    MUST respond with the single unified 403 regardless of .reason — see
    ADR-0024 §1 'Единое сообщение об отказе'."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def resolve_user_for_login(db: Session, claims: GoogleClaims, workspace_domain: str) -> User:
    if claims.hd is None or claims.hd != workspace_domain:
        raise LoginRejectedError("domain_mismatch")

    user = db.query(User).filter(User.google_sub == claims.sub).one_or_none()
    if user is None:
        candidate = db.query(User).filter(User.email == claims.email).one_or_none()
        if candidate is not None and candidate.google_sub is None:
            candidate.google_sub = claims.sub
            candidate.email = claims.email
            user = candidate
        else:
            raise LoginRejectedError("user_not_found")

    if not user.is_active:
        raise LoginRejectedError("user_inactive")

    return user


def create_session(db: Session, user: User) -> UserSession:
    now = utcnow()
    session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        csrf_token=uuid.uuid4().hex,
        created_at=now,
        expires_at=now + SESSION_IDLE_TTL,
        last_seen_at=now,
    )
    user.last_login_at = now
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_valid_session(db: Session, session_id: str) -> UserSession | None:
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        return None

    session = db.get(UserSession, session_uuid)
    if session is None:
        return None

    now = utcnow()
    expires_at = (
        session.expires_at
        if session.expires_at.tzinfo
        else session.expires_at.replace(tzinfo=timezone.utc)
    )
    created_at = (
        session.created_at
        if session.created_at.tzinfo
        else session.created_at.replace(tzinfo=timezone.utc)
    )
    if now > expires_at:
        return None
    if now > created_at + SESSION_ABSOLUTE_TTL:
        return None
    return session


def touch_session(db: Session, session: UserSession) -> None:
    now = utcnow()
    created_at = (
        session.created_at
        if session.created_at.tzinfo
        else session.created_at.replace(tzinfo=timezone.utc)
    )
    absolute_ceiling = created_at + SESSION_ABSOLUTE_TTL
    session.expires_at = min(now + SESSION_IDLE_TTL, absolute_ceiling)
    session.last_seen_at = now
    db.commit()


def delete_session(db: Session, session_id: str) -> None:
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        return
    session = db.get(UserSession, session_uuid)
    if session is not None:
        db.delete(session)
        db.commit()


def bootstrap_admin(db: Session, email: str) -> None:
    has_admin = db.query(User).filter(User.role == "admin").first() is not None
    if has_admin:
        return

    user = db.query(User).filter(User.email == email).one_or_none()
    if user is not None:
        user.role = "admin"
    else:
        user = User(email=email, role="admin", is_active=True, google_sub=None)
        db.add(user)
    db.commit()
