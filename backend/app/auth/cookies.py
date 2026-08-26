from datetime import datetime, timezone

from fastapi import Request, Response

from app.auth.constants import OAUTH_FLOW_TTL
from app.core.config import settings

OAUTH_FLOW_COOKIE = "oauth_flow"
SESSION_COOKIE = "session_id"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

_OAUTH_FLOW_SEPARATOR = "|"


def set_oauth_flow_cookie(response: Response, code_verifier: str, state: str) -> None:
    value = f"{code_verifier}{_OAUTH_FLOW_SEPARATOR}{state}"
    response.set_cookie(
        OAUTH_FLOW_COOKIE,
        value,
        max_age=int(OAUTH_FLOW_TTL.total_seconds()),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def read_oauth_flow_cookie(request: Request) -> tuple[str, str] | None:
    raw = request.cookies.get(OAUTH_FLOW_COOKIE)
    if raw is None or _OAUTH_FLOW_SEPARATOR not in raw:
        return None
    verifier, _, state = raw.partition(_OAUTH_FLOW_SEPARATOR)
    if not verifier or not state:
        return None
    return verifier, state


def clear_oauth_flow_cookie(response: Response) -> None:
    response.delete_cookie(
        OAUTH_FLOW_COOKIE, httponly=True, secure=settings.cookie_secure, samesite="lax"
    )


def set_session_cookies(response: Response, session_id: str, csrf_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, session_id, httponly=True, secure=settings.cookie_secure, samesite="lax"
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token, httponly=False, secure=settings.cookie_secure, samesite="lax"
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE, httponly=True, secure=settings.cookie_secure, samesite="lax"
    )
    response.delete_cookie(
        CSRF_COOKIE, httponly=False, secure=settings.cookie_secure, samesite="lax"
    )


def read_session_id(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def read_csrf_header(request: Request) -> str | None:
    return request.headers.get(CSRF_HEADER)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
