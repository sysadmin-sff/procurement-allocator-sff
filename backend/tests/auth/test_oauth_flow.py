import logging
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.auth.google import GoogleClaims
from app.core.config import settings
from app.main import app

client = TestClient(app, follow_redirects=False)

DOMAIN = "screen-factory-florida.com"


def _configure_settings(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", SecretStr("test-client-secret"))
    monkeypatch.setattr(settings, "google_workspace_domain", DOMAIN)


def test_login_redirects_to_google_and_sets_oauth_flow_cookie(monkeypatch):
    _configure_settings(monkeypatch)
    response = client.get("/auth/login")
    assert response.status_code == 307 or response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    assert parsed.hostname == "accounts.google.com"
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["test-client-id"]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["hd"] == [DOMAIN]
    assert "oauth_flow" in response.cookies


def test_login_without_google_settings_returns_500(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    monkeypatch.setattr(settings, "google_workspace_domain", None)
    response = client.get("/auth/login")
    assert response.status_code == 500


def test_callback_success_creates_session_and_sets_cookies(monkeypatch, db_session, make_user):
    _configure_settings(monkeypatch)
    make_user(email="freshlogin@screen-factory-florida.com", google_sub=None)

    login_resp = client.get("/auth/login")
    oauth_flow_cookie = login_resp.cookies["oauth_flow"]
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

    client.cookies.set("oauth_flow", oauth_flow_cookie)

    with (
        patch("app.api.auth._exchange_code_for_id_token", return_value="fake-id-token"),
        patch(
            "app.api.auth.verify_google_id_token",
            return_value=GoogleClaims(
                sub="new-google-sub",
                email="freshlogin@screen-factory-florida.com",
                name="Fresh Login",
                hd=DOMAIN,
            ),
        ),
    ):
        response = client.get(f"/auth/callback?code=fake-code&state={state}")

    assert response.status_code in (302, 307)
    assert response.headers["location"] == settings.frontend_url
    assert "session_id" in response.cookies
    assert "csrf_token" in response.cookies

    from app.models import User

    db, ids = db_session
    user = db.query(User).filter(User.email == "freshlogin@screen-factory-florida.com").one()
    ids.append(user.id)
    assert user.google_sub == "new-google-sub"
    assert user.last_login_at is not None


def test_callback_state_mismatch_returns_400(monkeypatch):
    _configure_settings(monkeypatch)
    login_resp = client.get("/auth/login")
    client.cookies.set("oauth_flow", login_resp.cookies["oauth_flow"])
    response = client.get("/auth/callback?code=fake-code&state=wrong-state")
    assert response.status_code == 400


def test_callback_missing_oauth_flow_cookie_returns_400(monkeypatch):
    _configure_settings(monkeypatch)
    client.cookies.clear()
    response = client.get("/auth/callback?code=fake-code&state=whatever")
    assert response.status_code == 400


def test_callback_domain_mismatch_returns_unified_403_and_logs_real_reason(monkeypatch, caplog):
    _configure_settings(monkeypatch)
    login_resp = client.get("/auth/login")
    client.cookies.set("oauth_flow", login_resp.cookies["oauth_flow"])
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

    with (
        patch("app.api.auth._exchange_code_for_id_token", return_value="fake-id-token"),
        patch(
            "app.api.auth.verify_google_id_token",
            return_value=GoogleClaims(
                sub="s1", email="x@othercompany.com", name=None, hd="othercompany.com"
            ),
        ),
        caplog.at_level(logging.WARNING),
    ):
        response = client.get(f"/auth/callback?code=fake-code&state={state}")

    assert response.status_code == 403
    assert "domain_mismatch" in caplog.text


def test_callback_user_not_found_returns_same_unified_403(monkeypatch, caplog):
    _configure_settings(monkeypatch)
    login_resp = client.get("/auth/login")
    client.cookies.set("oauth_flow", login_resp.cookies["oauth_flow"])
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

    with (
        patch("app.api.auth._exchange_code_for_id_token", return_value="fake-id-token"),
        patch(
            "app.api.auth.verify_google_id_token",
            return_value=GoogleClaims(
                sub="unknown", email="unknown@screen-factory-florida.com", name=None, hd=DOMAIN
            ),
        ),
        caplog.at_level(logging.WARNING),
    ):
        response = client.get(f"/auth/callback?code=fake-code&state={state}")

    assert response.status_code == 403
    assert response.text  # same body shape as domain-mismatch case
    assert "user_not_found" in caplog.text


def test_callback_inactive_user_returns_same_unified_403(monkeypatch, caplog, make_user):
    _configure_settings(monkeypatch)
    make_user(
        email="inactive@screen-factory-florida.com", google_sub="inactive-sub", is_active=False
    )

    login_resp = client.get("/auth/login")
    client.cookies.set("oauth_flow", login_resp.cookies["oauth_flow"])
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

    with (
        patch("app.api.auth._exchange_code_for_id_token", return_value="fake-id-token"),
        patch(
            "app.api.auth.verify_google_id_token",
            return_value=GoogleClaims(
                sub="inactive-sub",
                email="inactive@screen-factory-florida.com",
                name=None,
                hd=DOMAIN,
            ),
        ),
        caplog.at_level(logging.WARNING),
    ):
        response = client.get(f"/auth/callback?code=fake-code&state={state}")

    assert response.status_code == 403
    assert "user_inactive" in caplog.text


def test_me_unauthenticated_returns_401():
    fresh_client = TestClient(app)
    response = fresh_client.get("/auth/me")
    assert response.status_code == 401


def test_me_authenticated_returns_user(make_user, make_session):
    user = make_user(email="me-check@screen-factory-florida.com")
    user_session = make_session(user)
    fresh_client = TestClient(app)
    fresh_client.cookies.set("session_id", str(user_session.id))
    response = fresh_client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "me-check@screen-factory-florida.com"


def test_logout_deletes_session_row_and_second_request_401(make_user, make_session, db_session):
    user = make_user(email="logout-check@screen-factory-florida.com")
    user_session = make_session(user, csrf_token="logout-csrf")
    session_id = str(user_session.id)

    fresh_client = TestClient(app)
    fresh_client.cookies.set("session_id", session_id)
    response = fresh_client.post("/auth/logout", headers={"X-CSRF-Token": "logout-csrf"})
    assert response.status_code == 200

    db, _ = db_session
    from app.models import UserSession

    assert db.get(UserSession, user_session.id) is None

    second_client = TestClient(app)
    second_client.cookies.set("session_id", session_id)
    second_response = second_client.get("/auth/me")
    assert second_response.status_code == 401
