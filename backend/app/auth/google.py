from typing import NamedTuple

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token


class GoogleTokenInvalidError(Exception):
    """Raised when Google's id_token fails signature/iss/aud/exp verification."""


class GoogleClaims(NamedTuple):
    sub: str
    email: str
    name: str | None
    hd: str | None


def verify_google_id_token(id_token: str, client_id: str) -> GoogleClaims:
    """Verifies signature/iss/aud/exp via google-auth. Does NOT check the 'hd'
    claim against our workspace domain — that is a separate, explicit step
    the caller must perform (ADR-0024 §1 п.8; verify_oauth2_token does not
    do this itself)."""
    try:
        claims = google_id_token.verify_oauth2_token(
            id_token, google_requests.Request(), audience=client_id
        )
    except Exception as exc:
        raise GoogleTokenInvalidError(str(exc)) from exc

    return GoogleClaims(
        sub=claims["sub"],
        email=claims["email"],
        name=claims.get("name"),
        hd=claims.get("hd"),
    )
