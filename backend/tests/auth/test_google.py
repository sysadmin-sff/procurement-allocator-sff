from unittest.mock import patch

import pytest

from app.auth.google import GoogleTokenInvalidError, verify_google_id_token


def _claims(**overrides):
    base = {
        "sub": "1234567890",
        "email": "person@screen-factory-florida.com",
        "name": "Person Name",
        "hd": "screen-factory-florida.com",
    }
    base.update(overrides)
    return base


def test_verify_google_id_token_success():
    with patch("app.auth.google.google_id_token.verify_oauth2_token", return_value=_claims()):
        claims = verify_google_id_token("fake-token", client_id="client-123")
    assert claims.sub == "1234567890"
    assert claims.email == "person@screen-factory-florida.com"
    assert claims.name == "Person Name"
    assert claims.hd == "screen-factory-florida.com"


def test_verify_google_id_token_missing_hd_claim():
    with patch(
        "app.auth.google.google_id_token.verify_oauth2_token",
        return_value=_claims(hd=None),
    ):
        claims = verify_google_id_token("fake-token", client_id="client-123")
    assert claims.hd is None


def test_verify_google_id_token_raises_on_google_library_error():
    with patch(
        "app.auth.google.google_id_token.verify_oauth2_token",
        side_effect=ValueError("Token expired"),
    ):
        with pytest.raises(GoogleTokenInvalidError):
            verify_google_id_token("fake-token", client_id="client-123")
