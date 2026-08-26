import secrets
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.cookies import read_csrf_header, read_session_id
from app.auth.service import get_valid_session, touch_session
from app.core.database import get_db
from app.models import User

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    session_id = read_session_id(request)
    if session_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = get_valid_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if request.method in _MUTATING_METHODS:
        header_token = read_csrf_header(request)
        if header_token is None or not secrets.compare_digest(header_token, session.csrf_token):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")

    touch_session(db, session)
    return session.user


def require_role(role: str) -> Callable[[User], User]:
    def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role != role:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return _dependency
