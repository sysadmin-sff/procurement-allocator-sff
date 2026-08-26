from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import _csrf_token_matches, get_current_user, require_role
from app.core.database import get_db


@pytest.fixture
def probe_app(db_session):
    session, _ = db_session
    test_app = FastAPI()

    def _override_get_db():
        yield session

    test_app.dependency_overrides[get_db] = _override_get_db

    @test_app.get("/probe/me")
    def probe_me(user=Depends(get_current_user)):
        return {"email": user.email, "role": user.role}

    @test_app.post("/probe/mutate")
    def probe_mutate(user=Depends(get_current_user)):
        return {"ok": True}

    @test_app.get("/probe/admin-only")
    def probe_admin_only(user=Depends(require_role("admin"))):
        return {"ok": True}

    return TestClient(test_app)


def test_get_current_user_no_cookie_returns_401(probe_app):
    response = probe_app.get("/probe/me")
    assert response.status_code == 401


def test_get_current_user_invalid_session_id_returns_401(probe_app):
    probe_app.cookies.set("session_id", "00000000-0000-0000-0000-000000000000")
    response = probe_app.get("/probe/me")
    assert response.status_code == 401


def test_get_current_user_malformed_session_id_returns_401(probe_app):
    probe_app.cookies.set("session_id", "not-a-valid-uuid")
    response = probe_app.get("/probe/me")
    assert response.status_code == 401


def test_get_current_user_valid_session_returns_user(probe_app, make_user, make_session):
    user = make_user()
    user_session = make_session(user)
    probe_app.cookies.set("session_id", str(user_session.id))
    response = probe_app.get("/probe/me")
    assert response.status_code == 200
    assert response.json()["email"] == user.email


def test_post_without_csrf_header_returns_403(probe_app, make_user, make_session):
    user = make_user()
    user_session = make_session(user, csrf_token="secret-csrf")
    probe_app.cookies.set("session_id", str(user_session.id))
    response = probe_app.post("/probe/mutate")
    assert response.status_code == 403


def test_post_with_wrong_csrf_header_returns_403(probe_app, make_user, make_session):
    user = make_user()
    user_session = make_session(user, csrf_token="secret-csrf")
    probe_app.cookies.set("session_id", str(user_session.id))
    response = probe_app.post("/probe/mutate", headers={"X-CSRF-Token": "wrong-value"})
    assert response.status_code == 403


def test_post_with_non_ascii_csrf_header_returns_403(probe_app, make_user, make_session):
    # Starlette decodes raw header bytes as latin-1, so a header byte >= 0x80
    # (here the encoded "é" in "café-wrong-token") produces a non-ASCII `str`.
    # Pass raw bytes so httpx doesn't ascii-encode the header value itself,
    # matching what Starlette would actually hand to the app.
    user = make_user()
    user_session = make_session(user, csrf_token="secret-csrf")
    probe_app.cookies.set("session_id", str(user_session.id))
    response = probe_app.post(
        "/probe/mutate",
        headers={"X-CSRF-Token": "café-wrong-token".encode()},
    )
    assert response.status_code == 403


def test_post_with_empty_csrf_header_returns_403(probe_app, make_user, make_session):
    user = make_user()
    user_session = make_session(user, csrf_token="secret-csrf")
    probe_app.cookies.set("session_id", str(user_session.id))
    response = probe_app.post("/probe/mutate", headers={"X-CSRF-Token": ""})
    assert response.status_code == 403


def test_post_with_extremely_long_csrf_header_returns_403(probe_app, make_user, make_session):
    user = make_user()
    user_session = make_session(user, csrf_token="secret-csrf")
    probe_app.cookies.set("session_id", str(user_session.id))
    response = probe_app.post(
        "/probe/mutate", headers={"X-CSRF-Token": "a" * 1_000_000}
    )
    assert response.status_code == 403


def test_post_with_binary_garbage_csrf_header_returns_403(probe_app, make_user, make_session):
    # Raw bytes with no valid UTF-8/latin-1 text meaning at all, sent the same
    # way a byte-level fuzzer or a broken proxy might mangle a header.
    user = make_user()
    user_session = make_session(user, csrf_token="secret-csrf")
    probe_app.cookies.set("session_id", str(user_session.id))
    response = probe_app.post(
        "/probe/mutate",
        headers={"X-CSRF-Token": bytes(range(256))},
    )
    assert response.status_code == 403


def test_post_with_correct_csrf_header_succeeds(probe_app, make_user, make_session):
    user = make_user()
    user_session = make_session(user, csrf_token="secret-csrf")
    probe_app.cookies.set("session_id", str(user_session.id))
    response = probe_app.post("/probe/mutate", headers={"X-CSRF-Token": "secret-csrf"})
    assert response.status_code == 200


def test_get_without_csrf_header_is_not_blocked(probe_app, make_user, make_session):
    user = make_user()
    user_session = make_session(user)
    probe_app.cookies.set("session_id", str(user_session.id))
    response = probe_app.get("/probe/me")
    assert response.status_code == 200


def test_require_role_admin_on_employee_returns_403(probe_app, make_user, make_session):
    user = make_user(role="employee")
    user_session = make_session(user)
    probe_app.cookies.set("session_id", str(user_session.id))
    response = probe_app.get("/probe/admin-only")
    assert response.status_code == 403


def test_require_role_admin_on_admin_succeeds(probe_app, make_user, make_session):
    user = make_user(role="admin")
    user_session = make_session(user)
    probe_app.cookies.set("session_id", str(user_session.id))
    response = probe_app.get("/probe/admin-only")
    assert response.status_code == 200


# --- Direct unit tests on _csrf_token_matches: proving fail-closed-by-construction,
# not just fail-closed-for-every-input-we-thought-to-try. ---


def test_csrf_token_matches_none_header_returns_false():
    assert _csrf_token_matches(None, "secret-csrf") is False


def test_csrf_token_matches_empty_header_returns_false():
    assert _csrf_token_matches("", "secret-csrf") is False


def test_csrf_token_matches_correct_value_returns_true():
    assert _csrf_token_matches("secret-csrf", "secret-csrf") is True


def test_csrf_token_matches_wrong_value_returns_false():
    assert _csrf_token_matches("wrong-value", "secret-csrf") is False


def test_csrf_token_matches_returns_false_when_compare_digest_raises():
    # No real input reaches this branch today, but the guarantee is
    # structural: ANY exception during comparison must fail closed, not
    # propagate. Force the branch directly rather than hunting for an input
    # that happens to trigger it.
    with patch("app.auth.dependencies.secrets.compare_digest", side_effect=RuntimeError("boom")):
        assert _csrf_token_matches("secret-csrf", "secret-csrf") is False


def test_csrf_token_matches_returns_false_when_encode_raises():
    class _ExplodesOnEncode:
        def encode(self, *args, **kwargs):
            raise ValueError("boom")

    # session_token is normally a plain str (uuid4().hex per app.auth.service),
    # but the fail-closed guarantee must hold even if that ever changes.
    assert _csrf_token_matches("secret-csrf", _ExplodesOnEncode()) is False
