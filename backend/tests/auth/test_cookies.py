from fastapi import Response

from app.auth.cookies import (
    CSRF_COOKIE,
    OAUTH_FLOW_COOKIE,
    SESSION_COOKIE,
    set_oauth_flow_cookie,
    set_session_cookies,
)
from app.core.config import settings


def _secure_attr(response: Response, cookie_name: str) -> bool:
    header = next(
        v for k, v in response.raw_headers if k == b"set-cookie" and cookie_name.encode() in v
    )
    return b"Secure" in header


def test_session_cookies_are_secure_by_default(monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure", True)
    response = Response()
    set_session_cookies(response, "session-1", "csrf-1")

    assert _secure_attr(response, SESSION_COOKIE)
    assert _secure_attr(response, CSRF_COOKIE)


def test_session_cookies_omit_secure_when_disabled_for_dev(monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure", False)
    response = Response()
    set_session_cookies(response, "session-1", "csrf-1")

    assert not _secure_attr(response, SESSION_COOKIE)
    assert not _secure_attr(response, CSRF_COOKIE)


def test_oauth_flow_cookie_respects_cookie_secure_setting(monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure", False)
    response = Response()
    set_oauth_flow_cookie(response, "verifier", "state")

    assert not _secure_attr(response, OAUTH_FLOW_COOKIE)
