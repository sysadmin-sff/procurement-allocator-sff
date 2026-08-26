import logging
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.schemas.auth import MeOut
from app.auth.cookies import (
    clear_oauth_flow_cookie,
    clear_session_cookies,
    read_oauth_flow_cookie,
    set_oauth_flow_cookie,
    set_session_cookies,
)
from app.auth.dependencies import get_current_user
from app.auth.google import GoogleTokenInvalidError, verify_google_id_token
from app.auth.pkce import generate_pkce_pair, generate_state
from app.auth.service import (
    LoginRejectedError,
    create_session,
    delete_session,
    resolve_user_for_login,
)
from app.core.config import settings
from app.core.database import get_db
from app.models import User

router = APIRouter(prefix="/auth")

logger = logging.getLogger(__name__)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
UNIFIED_LOGIN_DENIED_DETAIL = "Access denied. Contact your administrator."


def _require_google_settings() -> tuple[str, str, str]:
    if (
        not settings.google_client_id
        or not settings.google_client_secret
        or not settings.google_workspace_domain
    ):
        raise HTTPException(status_code=500, detail="Google OAuth is not configured")
    return (
        settings.google_client_id,
        settings.google_client_secret,
        settings.google_workspace_domain,
    )


def _callback_redirect_uri(request: Request) -> str:
    return str(request.url_for("auth_callback"))


def _exchange_code_for_id_token(code: str, code_verifier: str, redirect_uri: str) -> str:
    client_id, client_secret, _ = _require_google_settings()
    response = httpx.post(
        GOOGLE_TOKEN_ENDPOINT,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()["id_token"]


@router.get("/login")
def login(request: Request) -> RedirectResponse:
    client_id, _, workspace_domain = _require_google_settings()

    code_verifier, code_challenge = generate_pkce_pair()
    state = generate_state()

    params = {
        "client_id": client_id,
        "redirect_uri": _callback_redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "hd": workspace_domain,
    }
    redirect = RedirectResponse(url=f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}")
    set_oauth_flow_cookie(redirect, code_verifier, state)
    return redirect


@router.get("/callback", name="auth_callback")
def callback(
    request: Request, code: str, state: str, db: Session = Depends(get_db)
) -> RedirectResponse:
    _, _, workspace_domain = _require_google_settings()

    flow = read_oauth_flow_cookie(request)
    if flow is None:
        raise HTTPException(
            status_code=400, detail="OAuth flow expired or missing, please try logging in again"
        )
    code_verifier, expected_state = flow
    if state != expected_state:
        raise HTTPException(
            status_code=400, detail="OAuth state mismatch, please try logging in again"
        )

    try:
        id_token = _exchange_code_for_id_token(
            code, code_verifier, _callback_redirect_uri(request)
        )
        claims = verify_google_id_token(id_token, client_id=settings.google_client_id)
    except (GoogleTokenInvalidError, httpx.HTTPError) as exc:
        logger.warning("OAuth callback token exchange/verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Could not verify login") from exc

    try:
        user = resolve_user_for_login(db, claims, workspace_domain)
    except LoginRejectedError as exc:
        logger.warning("Login rejected for email=%s reason=%s", claims.email, exc.reason)
        raise HTTPException(status_code=403, detail=UNIFIED_LOGIN_DENIED_DETAIL) from exc

    session = create_session(db, user)

    redirect = RedirectResponse(url="/")
    set_session_cookies(redirect, str(session.id), session.csrf_token)
    clear_oauth_flow_cookie(redirect)
    return redirect


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/logout")
def logout(
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    session_id = request.cookies.get("session_id")
    if session_id is not None:
        delete_session(db, session_id)
    clear_session_cookies(response)
    return {"status": "ok"}
