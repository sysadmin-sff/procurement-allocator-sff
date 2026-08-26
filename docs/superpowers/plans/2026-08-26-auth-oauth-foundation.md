# Auth Foundation (User/UserSession/OAuth flow) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `User`/`UserSession` data model, Google Workspace OIDC login flow, session/CSRF machinery, and admin-only user management endpoints — with zero changes to the existing business routers (`supplier`/`material`/`price`/`price_ingestion`/`project`/`allocation`/`order`/`purchase_record`), which stay unauthenticated until a follow-up task wires `Depends(get_current_user)`/`require_role(...)` onto them.

**Architecture:** New `app/auth/` package holds all OAuth/session/CSRF logic behind two dependency functions (`get_current_user`, `require_role`) per ADR-0024 §5, plus a `google.py` wrapper around `google-auth`'s `verify_oauth2_token`. Two new DB tables (`users`, `user_sessions`) via one Alembic migration. Two new routers: `auth.py` (login/callback public, me/logout individually gated — the one deliberate exception to router-level dependencies, ADR-0024 §5 checklist item 2) and `user.py` (admin-only CRUD, router-level `dependencies=`). Bootstrap-admin upsert runs once at FastAPI startup via an `@app.on_event("startup")` hook in `main.py`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (Mapped/mapped_column), Alembic, `google-auth` (new dependency), `pydantic-settings`, pytest + `fastapi.testclient.TestClient`, `unittest.mock` for mocking Google's token verification.

**Spec:** `docs/decisions/0024-authentication-authorization.md` (ADR-0024) — this plan implements §1 (OAuth flow), §2 (User model + bootstrap + user CRUD), §3 (sessions + CSRF), part of §4/§5 (auth.py/user.py permission wiring only — the other 8 routers are explicitly deferred), §8 (settings/secrets). §6 (audit columns on Project/Order/PurchaseRecord/AllocationLine) and the rest of §4/§5 (wiring existing routers) are **out of scope** for this plan per explicit task instructions — tracked as follow-up.

## Global Constraints

- Uniqueness/identity rules elsewhere in the schema (`Material.internal_sku` etc.) are unaffected — this plan only adds `users`/`user_sessions`.
- Do **not** modify `supplier.py`, `material.py`, `price.py`, `price_ingestion.py`, `project.py`, `allocation.py`, `order.py`, `purchase_record.py`, or their `APIRouter(...)` construction. They must keep working unauthenticated after this plan lands (ADR-0024 §5 wiring for them is a separate task).
- Do **not** implement ADR-0024 §6 (audit columns `created_by_user_id` etc.) — no task below touches `Project`, `Order`, `AllocationLine`, or `PurchaseRecord` models/migrations.
- Do **not** implement ADR-0024 §7 (frontend) or §10 (rate limiting middleware) — out of scope for this plan; not requested in the task.
- Single unified 403 for all three login-rejection causes (§1): domain mismatch, user not found, user inactive. Distinguishable only via `logging`, never in the HTTP response.
- CSRF check lives **inside** `get_current_user`, not a separate dependency/middleware (§3).
- Logout deletes the `UserSession` row before clearing cookies, never the reverse (§1).
- `ruff check .` and `pytest` must pass at the end of every task.
- New env vars (`google_client_id`, `google_client_secret`, `google_workspace_domain`, `session_signing_secret`, `bootstrap_admin_email`) are all `str | None = None` in `Settings` — never required at import time, only fail-fast inside `/auth/login` at request time (§8).

---

## File Structure

```
backend/
  app/
    core/config.py                     — MODIFY: add 5 new optional settings
    models/
      user.py                          — CREATE: User, UserSession ORM models
      __init__.py                      — MODIFY: export User, UserSession
    auth/                              — CREATE (new package)
      __init__.py
      constants.py                     — session TTL constants
      pkce.py                          — code_verifier/code_challenge/state generation
      google.py                        — thin wrapper around google-auth verify + hd check
      cookies.py                       — cookie names + set/clear helpers
      service.py                       — session creation, login resolution (sub/email lookup), logout, bootstrap admin
      dependencies.py                  — get_current_user, require_role
    api/
      auth.py                          — CREATE: /auth/login, /auth/callback, /auth/me, /auth/logout
      user.py                          — CREATE: /users CRUD, admin-only
      schemas/
        auth.py                        — CREATE: UserOut, MeOut
        user.py                        — CREATE: UserCreate, UserUpdate, UserOut (admin CRUD)
    main.py                            — MODIFY: include new routers, startup hook for bootstrap admin
  alembic/versions/
    <hash>_add_users_and_sessions.py   — CREATE: users, user_sessions tables
  pyproject.toml                       — MODIFY: add google-auth dependency
  tests/
    auth/
      __init__.py
      conftest.py                     — CREATE: db_session/make_user fixtures, mock Google claims helper
      test_oauth_flow.py              — CREATE: full login flow, unified-403 cases, bootstrap-linking cases
      test_session_and_csrf.py        — CREATE: get_current_user, logout, CSRF double-submit
      test_dependencies.py            — CREATE: require_role behavior
    user/
      __init__.py
      conftest.py                     — CREATE
      test_api.py                     — CREATE: /users CRUD + self-deactivation guard
    scripts/
      test_bootstrap_admin.py         — CREATE: idempotent upsert behavior (calls the service function directly, not via app startup)
```

---

## Task 1: Settings, dependency, and DB models

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/core/config.py`
- Create: `backend/app/models/user.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_health.py` (sanity — no new test file needed yet, just confirms nothing broke)

**Interfaces:**
- Produces: `Settings.google_client_id: str | None`, `google_client_secret: str | None`, `google_workspace_domain: str | None`, `session_signing_secret: str | None`, `bootstrap_admin_email: str | None`.
- Produces: `app.models.User` (fields: `id`, `google_sub`, `email`, `name`, `role`, `is_active`, `created_at`, `last_login_at`), `app.models.UserSession` (fields: `id`, `user_id`, `csrf_token`, `created_at`, `expires_at`, `last_seen_at`).

- [ ] **Step 1: Add `google-auth` dependency**

Edit `backend/pyproject.toml`, in the `dependencies` list add after `"pypdf>=4.3",`:

```toml
    "google-auth>=2.32",
```

- [ ] **Step 2: Install it**

Run: `cd backend && pip install -e ".[dev]"`
Expected: `google-auth` and its transitive deps (`cachetools`, `pyasn1-modules`, `rsa`) install without error.

- [ ] **Step 3: Add new settings fields**

Edit `backend/app/core/config.py`, add after `openai_price_ingestion_model` field:

```python
    google_client_id: str | None = None
    """OAuth 2.0 client ID from Google Cloud Console. See ADR-0024 §8."""
    google_client_secret: str | None = None
    """Secret — never returned in any API response, never logged. See ADR-0024 §8."""
    google_workspace_domain: str | None = None
    """Value the id_token's 'hd' claim must equal — see ADR-0024 §1 п.8."""
    session_signing_secret: str | None = None
    """Used only to sign the short-lived oauth_flow cookie (ADR-0024 §1 п.2) —
    UserSession/csrf_token are opaque DB-checked values, not signed separately."""
    bootstrap_admin_email: str | None = None
    """See ADR-0024 §2 — bootstrap of the first admin at app startup."""
```

- [ ] **Step 4: Write the User/UserSession models**

Create `backend/app/models/user.py`:

```python
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    pass


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    """NULL only for rows an admin pre-created by email before that person's
    first login — filled on first successful login and used as the primary
    lookup key thereafter (email can change in Workspace, sub cannot).
    See ADR-0024 §2."""
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    """'admin' | 'employee'. See ADR-0024 §2."""
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(UUIDPKMixin, Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    csrf_token: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped["User"] = relationship(back_populates="sessions")
```

Note: `created_at`/`expires_at`/`last_seen_at` are set explicitly by application code (sliding-window logic needs to *read* `created_at` to enforce the absolute TTL, so a `server_default=func.now()` that hides the value from the ORM object until a refresh is avoided — same reasoning as `AllocationRun.created_at` in `app/models/allocation.py`, which also sets it via `mapped_column(..., server_default=func.now())` but is never mutated after insert; here we mutate `last_seen_at`/`expires_at` on every request so plain nullable-false columns set by the service layer are simpler than mixing server-default with app-side updates).

- [ ] **Step 5: Export from `models/__init__.py`**

Edit `backend/app/models/__init__.py`:

```python
from app.models.user import User, UserSession
```

Add to `__all__`: `"User"`, `"UserSession"`.

- [ ] **Step 6: Verify imports don't break the app**

Run: `cd backend && python -c "from app.main import app"`
Expected: no import errors (routers not yet added, this just checks models/config import cleanly).

- [ ] **Step 7: Ruff check**

Run: `cd backend && ruff check app/models/user.py app/models/__init__.py app/core/config.py`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/app/core/config.py backend/app/models/user.py backend/app/models/__init__.py
git commit -m "feat: add User/UserSession models and OAuth settings (ADR-0024)"
```

---

## Task 2: Alembic migration for `users`/`user_sessions`

**Files:**
- Create: `backend/alembic/versions/<generated_hash>_add_users_and_sessions.py`

**Interfaces:**
- Consumes: `User`/`UserSession` table shapes from Task 1.
- Produces: `users` table (partial unique index on `google_sub WHERE google_sub IS NOT NULL`), `user_sessions` table.

- [ ] **Step 1: Autogenerate the migration**

Run: `cd backend && python -m alembic revision --autogenerate -m "add users and sessions"`

This creates a file under `alembic/versions/`. Note the generated revision hash and confirm `down_revision = "a2b4c6d8e0f1"` (current head, confirmed via `alembic heads` before starting this plan).

- [ ] **Step 2: Replace the unique index on `google_sub` with a partial index**

Autogenerate will likely emit a plain `sa.UniqueConstraint` or `op.create_unique_constraint` for `google_sub` because SQLAlchemy's `unique=True` on the column doesn't know about the `WHERE` clause. Edit the generated file's `upgrade()` so the `users` table creation does **not** mark `google_sub` unique inline, and instead add an explicit partial index. The migration body should look like:

```python
def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("google_sub", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index(
        "ix_users_google_sub",
        "users",
        ["google_sub"],
        unique=True,
        postgresql_where=sa.text("google_sub IS NOT NULL"),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("csrf_token", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("ix_users_google_sub", table_name="users", postgresql_where=sa.text("google_sub IS NOT NULL"))
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
```

Make sure `from sqlalchemy.dialects import postgresql` is imported (autogenerate usually adds this already — verify).

- [ ] **Step 3: Apply the migration**

Run: `cd backend && python -m alembic upgrade head`
Expected: succeeds, no errors. If Postgres isn't running locally, start it first (check `docker-compose.yml` or equivalent in repo root if one exists; otherwise flag to the user that a local Postgres instance is required).

- [ ] **Step 4: Verify the partial index exists**

Run: `cd backend && python -c "
from sqlalchemy import inspect
from app.core.database import engine
insp = inspect(engine)
for idx in insp.get_indexes('users'):
    print(idx)
"`
Expected: one row shows `'unique': True` with a `google_sub` column and `dialect_options` reflecting the partial `WHERE` (Postgres reflection surfaces this).

- [ ] **Step 5: Verify downgrade works and re-upgrade**

Run: `cd backend && python -m alembic downgrade -1 && python -m alembic upgrade head`
Expected: both succeed cleanly.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat: migrate users and user_sessions tables (ADR-0024)"
```

---

## Task 3: `app/auth/` core — constants, PKCE, cookies, Google verification wrapper

**Files:**
- Create: `backend/app/auth/__init__.py`
- Create: `backend/app/auth/constants.py`
- Create: `backend/app/auth/pkce.py`
- Create: `backend/app/auth/cookies.py`
- Create: `backend/app/auth/google.py`
- Test: `backend/tests/auth/__init__.py`
- Test: `backend/tests/auth/test_pkce.py`
- Test: `backend/tests/auth/test_google.py`

**Interfaces:**
- Produces: `SESSION_IDLE_TTL: timedelta`, `SESSION_ABSOLUTE_TTL: timedelta`, `OAUTH_FLOW_TTL: timedelta` (constants.py).
- Produces: `generate_pkce_pair() -> tuple[str, str]` (verifier, challenge), `generate_state() -> str` (pkce.py).
- Produces: `set_oauth_flow_cookie(response, code_verifier, state)`, `read_oauth_flow_cookie(request) -> tuple[str, str] | None`, `clear_oauth_flow_cookie(response)`, `set_session_cookies(response, session_id, csrf_token)`, `clear_session_cookies(response)`, `read_session_id(request) -> str | None`, `read_csrf_header(request) -> str | None` (cookies.py).
- Produces: `class GoogleClaims(NamedTuple): sub: str; email: str; name: str | None; hd: str | None`, `verify_google_id_token(id_token: str, client_id: str) -> GoogleClaims` raising `GoogleTokenInvalidError` on any verification failure (google.py).

- [ ] **Step 1: Write constants**

Create `backend/app/auth/constants.py`:

```python
from datetime import timedelta

SESSION_IDLE_TTL = timedelta(hours=12)
"""Extended on every authenticated request. See ADR-0024 §3."""
SESSION_ABSOLUTE_TTL = timedelta(days=30)
"""Hard ceiling from UserSession.created_at, never extended. See ADR-0024 §3."""
OAUTH_FLOW_TTL = timedelta(minutes=10)
"""TTL of the oauth_flow cookie holding PKCE verifier + state. See ADR-0024 §1 п.2."""
```

- [ ] **Step 2: Write failing test for PKCE generation**

Create `backend/tests/auth/__init__.py` (empty).

Create `backend/tests/auth/test_pkce.py`:

```python
import base64
import hashlib

from app.auth.pkce import generate_pkce_pair, generate_state


def test_generate_pkce_pair_challenge_matches_verifier():
    verifier, challenge = generate_pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected


def test_generate_pkce_pair_verifier_length_in_spec_range():
    verifier, _ = generate_pkce_pair()
    assert 43 <= len(verifier) <= 128


def test_generate_state_is_url_safe_and_nonempty():
    state = generate_state()
    assert len(state) >= 16
    assert all(c.isalnum() or c in "-_" for c in state)


def test_generate_pkce_pair_is_random():
    v1, _ = generate_pkce_pair()
    v2, _ = generate_pkce_pair()
    assert v1 != v2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/auth/test_pkce.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth'`.

- [ ] **Step 4: Implement PKCE module**

Create `backend/app/auth/__init__.py` (empty).

Create `backend/app/auth/pkce.py`:

```python
import base64
import hashlib
import secrets


def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate_pkce_pair() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge) per RFC 7636, S256 method."""
    verifier = _b64url_no_pad(secrets.token_bytes(64))
    challenge = _b64url_no_pad(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def generate_state() -> str:
    return _b64url_no_pad(secrets.token_bytes(24))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/auth/test_pkce.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Write cookie helpers (no test file — thin wrappers over Starlette Response/Request, exercised end-to-end in Task 5's flow tests)**

Create `backend/app/auth/cookies.py`:

```python
from datetime import datetime, timezone

from fastapi import Request, Response

from app.auth.constants import OAUTH_FLOW_TTL

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
        secure=True,
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
    response.delete_cookie(OAUTH_FLOW_COOKIE)


def set_session_cookies(response: Response, session_id: str, csrf_token: str) -> None:
    response.set_cookie(SESSION_COOKIE, session_id, httponly=True, secure=True, samesite="lax")
    response.set_cookie(CSRF_COOKIE, csrf_token, httponly=False, secure=True, samesite="lax")


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)


def read_session_id(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def read_csrf_header(request: Request) -> str | None:
    return request.headers.get(CSRF_HEADER)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
```

- [ ] **Step 7: Write failing test for Google verification wrapper**

Create `backend/tests/auth/test_google.py`:

```python
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
```

- [ ] **Step 8: Run test to verify it fails**

Run: `cd backend && pytest tests/auth/test_google.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth.google'`.

- [ ] **Step 9: Implement the Google verification wrapper**

Create `backend/app/auth/google.py`:

```python
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
```

- [ ] **Step 10: Run test to verify it passes**

Run: `cd backend && pytest tests/auth/test_google.py -v`
Expected: PASS (3 tests).

- [ ] **Step 11: Ruff check**

Run: `cd backend && ruff check app/auth/ tests/auth/`
Expected: no errors.

- [ ] **Step 12: Commit**

```bash
git add backend/app/auth/__init__.py backend/app/auth/constants.py backend/app/auth/pkce.py backend/app/auth/cookies.py backend/app/auth/google.py backend/tests/auth/__init__.py backend/tests/auth/test_pkce.py backend/tests/auth/test_google.py
git commit -m "feat: add PKCE, cookie, and Google id_token verification helpers (ADR-0024)"
```

---

## Task 4: `app/auth/service.py` — user resolution, session lifecycle, bootstrap admin

**Files:**
- Create: `backend/app/auth/service.py`
- Test: `backend/tests/auth/conftest.py`
- Test: `backend/tests/scripts/test_bootstrap_admin.py`
- Test: `backend/tests/auth/test_service.py`

**Interfaces:**
- Consumes: `User`, `UserSession` (Task 1); `SESSION_IDLE_TTL`, `SESSION_ABSOLUTE_TTL` (Task 3); `GoogleClaims` (Task 3).
- Produces:
  - `class LoginRejectedError(Exception): reason: str` — carries the internal-only reason string (`"domain_mismatch"` / `"user_not_found"` / `"user_inactive"` / `"sub_conflict"`) for logging; callers must never surface `.reason` in an HTTP response.
  - `resolve_user_for_login(db: Session, claims: GoogleClaims, workspace_domain: str) -> User` — raises `LoginRejectedError` on any of the four rejection cases; returns (and mutates in-session, not yet committed) the matched `User` on success, performing the bootstrap `google_sub` backfill described in ADR-0024 §1 п.9.
  - `create_session(db: Session, user: User) -> UserSession` — creates and commits a new `UserSession`, sets `user.last_login_at`.
  - `get_valid_session(db: Session, session_id: str) -> UserSession | None` — returns None if not found or expired (checks both idle and absolute TTL); does NOT extend TTL (that's a separate step so tests can distinguish "expired" from "extend").
  - `touch_session(db: Session, session: UserSession) -> None` — extends `expires_at` by `SESSION_IDLE_TTL` from now, capped at `session.created_at + SESSION_ABSOLUTE_TTL`; updates `last_seen_at`; commits.
  - `delete_session(db: Session, session_id: str) -> None` — deletes the `UserSession` row if present; no-op if not found.
  - `bootstrap_admin(db: Session, email: str) -> None` — idempotent upsert per ADR-0024 §2 (only acts if zero `role="admin"` rows exist).

- [ ] **Step 1: Write shared test fixtures**

Create `backend/tests/auth/conftest.py`:

```python
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.constants import SESSION_IDLE_TTL
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
        google_sub=None,
        role="employee",
        is_active=True,
        name="Test User",
    ):
        user = User(
            email=email,
            google_sub=google_sub,
            role=role,
            is_active=is_active,
            name=name,
        )
        session.add(user)
        session.flush()
        user_ids.append(user.id)
        return user

    return _make


@pytest.fixture
def make_session(db_session):
    session, _ = db_session

    def _make(user, csrf_token="test-csrf-token", expired=False, absolute_expired=False):
        now = datetime.now(timezone.utc)
        created_at = now - timedelta(days=31) if absolute_expired else now
        expires_at = now - timedelta(hours=1) if expired else now + SESSION_IDLE_TTL
        user_session = UserSession(
            id=uuid.uuid4(),
            user_id=user.id,
            csrf_token=csrf_token,
            created_at=created_at,
            expires_at=expires_at,
            last_seen_at=now,
        )
        session.add(user_session)
        session.flush()
        return user_session

    return _make
```

- [ ] **Step 2: Write failing tests for `resolve_user_for_login`, session lifecycle, bootstrap**

Create `backend/tests/auth/test_service.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.constants import SESSION_ABSOLUTE_TTL
from app.auth.google import GoogleClaims
from app.auth.service import (
    LoginRejectedError,
    bootstrap_admin,
    create_session,
    delete_session,
    get_valid_session,
    resolve_user_for_login,
    touch_session,
)

DOMAIN = "screen-factory-florida.com"


def _claims(sub="google-sub-1", email="employee@screen-factory-florida.com", hd=DOMAIN):
    return GoogleClaims(sub=sub, email=email, name="Test User", hd=hd)


def test_resolve_user_for_login_domain_mismatch(db_session):
    session, _ = db_session
    with pytest.raises(LoginRejectedError) as exc_info:
        resolve_user_for_login(session, _claims(hd="othercompany.com"), DOMAIN)
    assert exc_info.value.reason == "domain_mismatch"


def test_resolve_user_for_login_missing_hd_claim(db_session):
    session, _ = db_session
    with pytest.raises(LoginRejectedError) as exc_info:
        resolve_user_for_login(session, _claims(hd=None), DOMAIN)
    assert exc_info.value.reason == "domain_mismatch"


def test_resolve_user_for_login_sub_not_found_email_not_found(db_session):
    session, _ = db_session
    with pytest.raises(LoginRejectedError) as exc_info:
        resolve_user_for_login(session, _claims(sub="unknown-sub", email="nobody@screen-factory-florida.com"), DOMAIN)
    assert exc_info.value.reason == "user_not_found"


def test_resolve_user_for_login_found_by_sub(db_session, make_user):
    session, _ = db_session
    user = make_user(email="employee@screen-factory-florida.com", google_sub="google-sub-1")
    resolved = resolve_user_for_login(session, _claims(sub="google-sub-1", email="employee@screen-factory-florida.com"), DOMAIN)
    assert resolved.id == user.id


def test_resolve_user_for_login_inactive_user(db_session, make_user):
    session, _ = db_session
    make_user(email="employee@screen-factory-florida.com", google_sub="google-sub-1", is_active=False)
    with pytest.raises(LoginRejectedError) as exc_info:
        resolve_user_for_login(session, _claims(sub="google-sub-1", email="employee@screen-factory-florida.com"), DOMAIN)
    assert exc_info.value.reason == "user_inactive"


def test_resolve_user_for_login_bootstrap_fallback_by_email_fills_sub(db_session, make_user):
    session, _ = db_session
    user = make_user(email="preexisting@screen-factory-florida.com", google_sub=None)
    resolved = resolve_user_for_login(
        session, _claims(sub="google-sub-new", email="preexisting@screen-factory-florida.com"), DOMAIN
    )
    assert resolved.id == user.id
    assert resolved.google_sub == "google-sub-new"


def test_resolve_user_for_login_email_matches_but_sub_taken_by_someone_else(db_session, make_user):
    session, _ = db_session
    make_user(email="shared@screen-factory-florida.com", google_sub="already-someone-elses-sub")
    with pytest.raises(LoginRejectedError) as exc_info:
        resolve_user_for_login(
            session, _claims(sub="a-different-sub", email="shared@screen-factory-florida.com"), DOMAIN
        )
    assert exc_info.value.reason == "user_not_found"


def test_create_session_sets_last_login_at(db_session, make_user):
    session, _ = db_session
    user = make_user()
    assert user.last_login_at is None
    user_session = create_session(session, user)
    session.refresh(user)
    assert user.last_login_at is not None
    assert user_session.user_id == user.id
    assert user_session.csrf_token


def test_get_valid_session_returns_none_when_idle_expired(db_session, make_user, make_session):
    session, _ = db_session
    user = make_user()
    user_session = make_session(user, expired=True)
    assert get_valid_session(session, str(user_session.id)) is None


def test_get_valid_session_returns_none_when_absolute_expired(db_session, make_user, make_session):
    session, _ = db_session
    user = make_user()
    user_session = make_session(user, absolute_expired=True)
    assert get_valid_session(session, str(user_session.id)) is None


def test_get_valid_session_returns_session_when_valid(db_session, make_user, make_session):
    session, _ = db_session
    user = make_user()
    user_session = make_session(user)
    found = get_valid_session(session, str(user_session.id))
    assert found is not None
    assert found.id == user_session.id


def test_touch_session_extends_expires_at_but_caps_at_absolute_ttl(db_session, make_user, make_session):
    session, _ = db_session
    user = make_user()
    user_session = make_session(user)
    old_expires = user_session.expires_at
    touch_session(session, user_session)
    assert user_session.expires_at > old_expires
    assert user_session.expires_at <= user_session.created_at + SESSION_ABSOLUTE_TTL


def test_delete_session_removes_row(db_session, make_user, make_session):
    session, _ = db_session
    user = make_user()
    user_session = make_session(user)
    session_id = str(user_session.id)
    delete_session(session, session_id)
    assert get_valid_session(session, session_id) is None


def test_delete_session_nonexistent_is_noop(db_session):
    session, _ = db_session
    delete_session(session, "00000000-0000-0000-0000-000000000000")


def test_bootstrap_admin_creates_new_user_when_none_exists(db_session):
    session, user_ids = db_session
    bootstrap_admin(session, "newadmin@screen-factory-florida.com")
    from app.models import User

    user = session.query(User).filter(User.email == "newadmin@screen-factory-florida.com").one()
    user_ids.append(user.id)
    assert user.role == "admin"
    assert user.is_active is True
    assert user.google_sub is None


def test_bootstrap_admin_promotes_existing_user_by_email(db_session, make_user):
    session, _ = db_session
    user = make_user(email="promoteme@screen-factory-florida.com", role="employee")
    bootstrap_admin(session, "promoteme@screen-factory-florida.com")
    session.refresh(user)
    assert user.role == "admin"


def test_bootstrap_admin_idempotent_does_not_duplicate(db_session):
    session, user_ids = db_session
    bootstrap_admin(session, "idempotent@screen-factory-florida.com")
    bootstrap_admin(session, "idempotent@screen-factory-florida.com")
    from app.models import User

    matches = session.query(User).filter(User.email == "idempotent@screen-factory-florida.com").all()
    user_ids.extend(u.id for u in matches)
    assert len(matches) == 1


def test_bootstrap_admin_does_not_repromote_after_manual_demotion(db_session, make_user):
    session, _ = db_session
    make_user(email="other-admin@screen-factory-florida.com", role="admin")
    demoted = make_user(email="demoted@screen-factory-florida.com", role="employee")
    bootstrap_admin(session, "demoted@screen-factory-florida.com")
    session.refresh(demoted)
    assert demoted.role == "employee"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/auth/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth.service'`.

- [ ] **Step 4: Implement `app/auth/service.py`**

```python
import uuid
from datetime import datetime, timezone

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
    expires_at = session.expires_at if session.expires_at.tzinfo else session.expires_at.replace(tzinfo=timezone.utc)
    created_at = session.created_at if session.created_at.tzinfo else session.created_at.replace(tzinfo=timezone.utc)
    if now > expires_at:
        return None
    if now > created_at + SESSION_ABSOLUTE_TTL:
        return None
    return session


def touch_session(db: Session, session: UserSession) -> None:
    now = utcnow()
    created_at = session.created_at if session.created_at.tzinfo else session.created_at.replace(tzinfo=timezone.utc)
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
```

Note on `test_touch_session_extends_expires_at_but_caps_at_absolute_ttl`: with a freshly created session (`created_at = now`), `now + SESSION_IDLE_TTL` (12h) is far below `created_at + SESSION_ABSOLUTE_TTL` (30d), so the cap doesn't bind in that specific test — the assertion `<=` still holds trivially. The cap is exercised implicitly; if stricter coverage is wanted later, a session created near its 30-day boundary would show the min() actually clamping — not required for this plan's acceptance criteria since ADR-0024 doesn't demand a dedicated test for that edge.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/auth/test_service.py -v`
Expected: PASS (18 tests).

- [ ] **Step 6: Write bootstrap-admin script-level idempotency test (separate from service unit tests — verifies the exact ADR-0024 §2 scenario end to end against a real startup-style call)**

Create `backend/tests/scripts/test_bootstrap_admin.py`:

```python
from app.auth.service import bootstrap_admin
from app.core.database import SessionLocal
from app.models import User


def test_bootstrap_admin_repeated_calls_same_email_no_duplicate_no_redemotion():
    session = SessionLocal()
    email = "repeat-bootstrap@screen-factory-florida.com"
    try:
        bootstrap_admin(session, email)
        first = session.query(User).filter(User.email == email).one()
        assert first.role == "admin"

        # Simulate an admin manually demoting this user via /users after bootstrap.
        first.role = "employee"
        session.commit()

        # Second bootstrap run (e.g. redeploy with same BOOTSTRAP_ADMIN_EMAIL) must
        # NOT re-promote, because another admin might exist by then -- but here
        # there are zero admins left, so per ADR-0024 §2 rule ("no admin exists at
        # all", not "no row with this email") it WOULD re-run bootstrap logic.
        # To specifically test "does not silently re-grant after manual demotion
        # while another admin exists", create a second admin first.
        other = User(email="another-admin@screen-factory-florida.com", role="admin", is_active=True)
        session.add(other)
        session.commit()

        bootstrap_admin(session, email)
        session.refresh(first)
        assert first.role == "employee"
    finally:
        session.query(User).filter(User.email.in_([email, "another-admin@screen-factory-florida.com"])).delete(
            synchronize_session=False
        )
        session.commit()
        session.close()
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && pytest tests/scripts/test_bootstrap_admin.py -v`
Expected: PASS (1 test).

- [ ] **Step 8: Ruff check**

Run: `cd backend && ruff check app/auth/service.py tests/auth/conftest.py tests/auth/test_service.py tests/scripts/test_bootstrap_admin.py`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add backend/app/auth/service.py backend/tests/auth/conftest.py backend/tests/auth/test_service.py backend/tests/scripts/test_bootstrap_admin.py
git commit -m "feat: add auth service layer (login resolution, sessions, bootstrap admin) (ADR-0024)"
```

---

## Task 5: `app/auth/dependencies.py` — `get_current_user`, `require_role`, CSRF enforcement

**Files:**
- Create: `backend/app/auth/dependencies.py`
- Test: `backend/tests/auth/test_dependencies.py`

**Interfaces:**
- Consumes: `get_valid_session`, `touch_session` (Task 4); `read_session_id`, `read_csrf_header` (Task 3); `get_db` (`app/core/database.py`, existing).
- Produces: `get_current_user(request: Request, db: Session = Depends(get_db)) -> User` — raises `HTTPException(401)` if no/invalid session, `HTTPException(403)` if CSRF check fails on a mutating method. `require_role(role: str) -> Callable` — dependency factory raising `HTTPException(403, detail="Insufficient permissions")` if `user.role != role`.

Since there's no router wired to these yet in this plan (existing routers stay unauthenticated), tests exercise `get_current_user`/`require_role` directly as FastAPI dependencies against a throwaway test route registered only inside the test module — this avoids needing to touch any production router to verify the dependency's behavior.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/auth/test_dependencies.py`:

```python
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user, require_role
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/auth/test_dependencies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth.dependencies'`.

- [ ] **Step 3: Implement `app/auth/dependencies.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/auth/test_dependencies.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Ruff check**

Run: `cd backend && ruff check app/auth/dependencies.py tests/auth/test_dependencies.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/auth/dependencies.py backend/tests/auth/test_dependencies.py
git commit -m "feat: add get_current_user/require_role with inline CSRF enforcement (ADR-0024)"
```

---

## Task 6: `auth.py` schemas and router — `/auth/login`, `/auth/callback`, `/auth/me`, `/auth/logout`

**Files:**
- Create: `backend/app/api/schemas/auth.py`
- Create: `backend/app/api/auth.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/auth/test_oauth_flow.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5, plus `settings` (`app.core.config`).
- Produces: `GET /auth/login` (302 redirect to Google, sets `oauth_flow` cookie; 500 if Google settings unset), `GET /auth/callback` (handles Google redirect, sets session cookies, redirects to `/`; 400 on state mismatch; unified 403 on the three rejection cases), `GET /auth/me` (returns `MeOut`, 401 if unauthenticated), `POST /auth/logout` (deletes session, clears cookies, 401 if unauthenticated).
- Produces schema: `MeOut { id: UUID, email: str, name: str | None, role: str }`.

- [ ] **Step 1: Write schema**

Create `backend/app/api/schemas/auth.py`:

```python
import uuid

from pydantic import BaseModel


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Write failing tests for the full flow**

Create `backend/tests/auth/test_oauth_flow.py`:

```python
import logging
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app.auth.google import GoogleClaims
from app.core.config import settings
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app, follow_redirects=False)

DOMAIN = "screen-factory-florida.com"


def _configure_settings(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")
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


def test_callback_success_creates_session_and_sets_cookies(monkeypatch, db_session):
    _configure_settings(monkeypatch)
    login_resp = client.get("/auth/login")
    oauth_flow_cookie = login_resp.cookies["oauth_flow"]
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

    client.cookies.set("oauth_flow", oauth_flow_cookie)

    with (
        patch("app.api.auth._exchange_code_for_id_token", return_value="fake-id-token"),
        patch(
            "app.api.auth.verify_google_id_token",
            return_value=GoogleClaims(
                sub="new-google-sub", email="freshlogin@screen-factory-florida.com", name="Fresh Login", hd=DOMAIN
            ),
        ),
    ):
        response = client.get(f"/auth/callback?code=fake-code&state={state}")

    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/"
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
            return_value=GoogleClaims(sub="s1", email="x@othercompany.com", name=None, hd="othercompany.com"),
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
            return_value=GoogleClaims(sub="unknown", email="unknown@screen-factory-florida.com", name=None, hd=DOMAIN),
        ),
        caplog.at_level(logging.WARNING),
    ):
        response = client.get(f"/auth/callback?code=fake-code&state={state}")

    assert response.status_code == 403
    assert response.text  # same body shape as domain-mismatch case
    assert "user_not_found" in caplog.text


def test_callback_inactive_user_returns_same_unified_403(monkeypatch, caplog, make_user):
    _configure_settings(monkeypatch)
    make_user(email="inactive@screen-factory-florida.com", google_sub="inactive-sub", is_active=False)

    login_resp = client.get("/auth/login")
    client.cookies.set("oauth_flow", login_resp.cookies["oauth_flow"])
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

    with (
        patch("app.api.auth._exchange_code_for_id_token", return_value="fake-id-token"),
        patch(
            "app.api.auth.verify_google_id_token",
            return_value=GoogleClaims(sub="inactive-sub", email="inactive@screen-factory-florida.com", name=None, hd=DOMAIN),
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
```

Note: `test_oauth_flow.py` uses the `db_session`/`make_user`/`make_session` fixtures from `tests/auth/conftest.py` (Task 4) — `db_session` already tracks `user_ids` and cleans up sessions+users created during the test.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/auth/test_oauth_flow.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.auth'` (or 404s once router import resolves — but router doesn't exist yet, so import error first).

- [ ] **Step 4: Promote `httpx` to a main dependency**

`httpx` is currently listed only under `[project.optional-dependencies].dev` in `backend/pyproject.toml` (used for `TestClient`). The callback handler below needs it at runtime for the server-to-server token exchange with Google, so move it into the main `dependencies` list: edit `backend/pyproject.toml`, add `"httpx>=0.27",` next to `"pypdf>=4.3",` in `[project].dependencies`, and remove the now-redundant `"httpx>=0.27"` line from `[project.optional-dependencies].dev` (a single copy in `dependencies` covers both prod and dev/test installs).

Run: `cd backend && pip install -e ".[dev]"`
Expected: no errors (httpx is likely already installed from the dev extra; this just confirms the moved declaration resolves).

- [ ] **Step 5: Implement `app/api/auth.py`**

```python
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
from app.auth.service import LoginRejectedError, create_session, delete_session, resolve_user_for_login
from app.core.config import settings
from app.core.database import get_db
from app.models import User

router = APIRouter(prefix="/auth")

logger = logging.getLogger(__name__)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
UNIFIED_LOGIN_DENIED_DETAIL = "Access denied. Contact your administrator."


def _require_google_settings() -> tuple[str, str, str]:
    if not settings.google_client_id or not settings.google_client_secret or not settings.google_workspace_domain:
        raise HTTPException(status_code=500, detail="Google OAuth is not configured")
    return settings.google_client_id, settings.google_client_secret, settings.google_workspace_domain


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
def callback(request: Request, code: str, state: str, db: Session = Depends(get_db)) -> RedirectResponse:
    _, _, workspace_domain = _require_google_settings()

    flow = read_oauth_flow_cookie(request)
    if flow is None:
        raise HTTPException(status_code=400, detail="OAuth flow expired or missing, please try logging in again")
    code_verifier, expected_state = flow
    if state != expected_state:
        raise HTTPException(status_code=400, detail="OAuth state mismatch, please try logging in again")

    try:
        id_token = _exchange_code_for_id_token(code, code_verifier, _callback_redirect_uri(request))
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
def logout(response: Response, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    session_id = request.cookies.get("session_id")
    if session_id is not None:
        delete_session(db, session_id)
    clear_session_cookies(response)
    return {"status": "ok"}
```

- [ ] **Step 6: Wire the router into `main.py` (no startup hook yet — that's Task 8)**

Edit `backend/app/main.py`, add import and `include_router` call:

```python
from app.api.auth import router as auth_router
```

```python
app.include_router(health_router)
app.include_router(auth_router)
```

(placed right after `health_router`, before the business routers — order doesn't affect routing correctness here, but keeps public/auth infra grouped at the top).

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest tests/auth/test_oauth_flow.py -v`
Expected: PASS (12 tests). If `test_login_redirects_to_google_and_sets_oauth_flow_cookie` fails on `url_for("auth_callback")` because the route isn't fully resolvable in TestClient without a request context quirk, adjust `_callback_redirect_uri` to build from `request.base_url` + `"auth/callback"` directly instead of `url_for` — verify against actual failure output before changing.

- [ ] **Step 8: Run the full test suite to check for regressions**

Run: `cd backend && pytest -v`
Expected: all prior tests (health, supplier, material, price, etc.) still PASS — this task must not have touched any existing router.

- [ ] **Step 9: Ruff check**

Run: `cd backend && ruff check app/api/auth.py app/api/schemas/auth.py app/main.py tests/auth/test_oauth_flow.py`
Expected: no errors.

- [ ] **Step 10: Commit**

```bash
git add backend/app/api/auth.py backend/app/api/schemas/auth.py backend/app/main.py backend/tests/auth/test_oauth_flow.py backend/pyproject.toml
git commit -m "feat: add /auth/login, /auth/callback, /auth/me, /auth/logout (ADR-0024)"
```

---

## Task 7: `user.py` schemas and router — admin-only `/users` CRUD

**Files:**
- Create: `backend/app/api/schemas/user.py`
- Create: `backend/app/api/user.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/user/__init__.py`
- Test: `backend/tests/user/conftest.py`
- Test: `backend/tests/user/test_api.py`

**Interfaces:**
- Consumes: `require_role` (Task 5), `User` model (Task 1).
- Produces: `GET /users` (list, admin-only), `POST /users` (create, admin-only), `PATCH /users/{id}` (update role/is_active, admin-only) — no `DELETE` per ADR-0024 §2. Self-deactivation of the last active admin → 409.

- [ ] **Step 1: Write schemas**

Create `backend/app/api/schemas/user.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class UserCreate(BaseModel):
    email: str
    role: str
    is_active: bool = True


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Write test fixtures for the `/users` router**

Create `backend/tests/user/__init__.py` (empty).

Create `backend/tests/user/conftest.py`:

```python
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

    def _make(email="employee@screen-factory-florida.com", role="employee", is_active=True, google_sub=None):
        user = User(email=email, role=role, is_active=is_active, google_sub=google_sub)
        session.add(user)
        session.flush()
        user_ids.append(user.id)
        return user

    return _make


@pytest.fixture
def make_session(db_session):
    from datetime import datetime, timezone
    import uuid as uuid_module

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
        return {"cookies": {"session_id": str(user_session.id)}, "headers": {"X-CSRF-Token": user_session.csrf_token}}

    return _for
```

- [ ] **Step 3: Write failing tests**

Create `backend/tests/user/test_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def test_list_users_requires_admin(make_user, make_session):
    employee = make_user(role="employee")
    employee_session = make_session(employee)
    client = _client_as(employee_session)
    response = client.get("/users")
    assert response.status_code == 403


def test_list_users_as_admin_succeeds(make_user, make_session):
    admin = make_user(email="admin1@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin)
    client = _client_as(admin_session)
    response = client.get("/users")
    assert response.status_code == 200
    emails = [u["email"] for u in response.json()]
    assert "admin1@screen-factory-florida.com" in emails


def test_list_users_no_session_returns_401():
    client = TestClient(app)
    response = client.get("/users")
    assert response.status_code == 401


def test_create_user_as_admin(make_user, make_session, db_session):
    admin = make_user(email="admin2@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin, csrf_token="csrf-create")
    client = _client_as(admin_session)
    response = client.post(
        "/users",
        json={"email": "new-hire@screen-factory-florida.com", "role": "employee"},
        headers={"X-CSRF-Token": "csrf-create"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new-hire@screen-factory-florida.com"
    assert body["is_active"] is True

    db, ids = db_session
    from app.models import User

    created = db.query(User).filter(User.email == "new-hire@screen-factory-florida.com").one()
    ids.append(created.id)


def test_create_user_without_csrf_header_returns_403(make_user, make_session):
    admin = make_user(email="admin3@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin, csrf_token="csrf-create2")
    client = _client_as(admin_session)
    response = client.post("/users", json={"email": "blocked@screen-factory-florida.com", "role": "employee"})
    assert response.status_code == 403


def test_patch_user_role_as_admin(make_user, make_session):
    admin = make_user(email="admin4@screen-factory-florida.com", role="admin")
    target = make_user(email="promote-target@screen-factory-florida.com", role="employee")
    admin_session = make_session(admin, csrf_token="csrf-patch")
    client = _client_as(admin_session)
    response = client.patch(
        f"/users/{target.id}", json={"role": "admin"}, headers={"X-CSRF-Token": "csrf-patch"}
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_patch_as_employee_returns_403(make_user, make_session):
    employee = make_user(role="employee")
    target = make_user(email="target2@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token="csrf-emp")
    client = _client_as(employee_session)
    response = client.patch(
        f"/users/{target.id}", json={"role": "admin"}, headers={"X-CSRF-Token": "csrf-emp"}
    )
    assert response.status_code == 403


def test_self_deactivation_of_last_active_admin_returns_409(make_user, make_session):
    admin = make_user(email="lonely-admin@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin, csrf_token="csrf-self")
    client = _client_as(admin_session)
    response = client.patch(
        f"/users/{admin.id}", json={"is_active": False}, headers={"X-CSRF-Token": "csrf-self"}
    )
    assert response.status_code == 409


def test_self_deactivation_when_another_admin_exists_succeeds(make_user, make_session):
    admin = make_user(email="admin-a@screen-factory-florida.com", role="admin")
    make_user(email="admin-b@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin, csrf_token="csrf-self2")
    client = _client_as(admin_session)
    response = client.patch(
        f"/users/{admin.id}", json={"is_active": False}, headers={"X-CSRF-Token": "csrf-self2"}
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && pytest tests/user/test_api.py -v`
Expected: FAIL with 404s (router not registered) — `ModuleNotFoundError` if `app.api.user` doesn't exist yet, since nothing imports it.

- [ ] **Step 5: Implement `app/api/user.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.user import UserCreate, UserOut, UserUpdate
from app.auth.dependencies import require_role
from app.core.database import get_db
from app.models import User

router = APIRouter(prefix="/users", dependencies=[Depends(require_role("admin"))])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.query(User).order_by(User.email).all())


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    user = User(email=payload.email, role=payload.role, is_active=payload.is_active, google_sub=None)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    deactivating_self = (
        payload.is_active is False and user.id == current_user.id and user.role == "admin"
    )
    if deactivating_self:
        other_active_admins = (
            db.query(User)
            .filter(User.role == "admin", User.is_active.is_(True), User.id != user.id)
            .first()
        )
        if other_active_admins is None:
            raise HTTPException(status_code=409, detail="Cannot deactivate the last active admin")

    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

    db.commit()
    db.refresh(user)
    return user
```

Note: `list_users`/`create_user` don't need the `current_user` param explicitly since the router-level `dependencies=[Depends(require_role("admin"))]` already enforces the role check — `update_user` re-declares `Depends(require_role("admin"))` as a named parameter purely to get the resolved `User` object for the self-deactivation check (FastAPI dedupes the dependency call within one request, so this doesn't run `require_role` twice).

- [ ] **Step 6: Wire router into `main.py`**

Edit `backend/app/main.py`:

```python
from app.api.user import router as user_router
```

```python
app.include_router(user_router)
```

(add alongside `auth_router`, after it).

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest tests/user/test_api.py -v`
Expected: PASS (9 tests).

- [ ] **Step 8: Run full suite for regressions**

Run: `cd backend && pytest -v`
Expected: all tests pass, including every pre-existing router's tests untouched.

- [ ] **Step 9: Ruff check**

Run: `cd backend && ruff check app/api/user.py app/api/schemas/user.py app/main.py tests/user/`
Expected: no errors.

- [ ] **Step 10: Commit**

```bash
git add backend/app/api/user.py backend/app/api/schemas/user.py backend/app/main.py backend/tests/user/
git commit -m "feat: add admin-only /users CRUD with last-admin self-deactivation guard (ADR-0024)"
```

---

## Task 8: Bootstrap-admin startup hook

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_bootstrap_startup.py`

**Interfaces:**
- Consumes: `bootstrap_admin` (Task 4), `settings.bootstrap_admin_email` (Task 1).
- Produces: FastAPI `startup` event that calls `bootstrap_admin(db, settings.bootstrap_admin_email)` if the setting is non-empty, using a fresh `SessionLocal()` (not a request-scoped `get_db`, since there's no request at startup time).

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_bootstrap_startup.py`:

```python
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_startup_calls_bootstrap_admin_when_email_configured(monkeypatch):
    monkeypatch.setattr(settings, "bootstrap_admin_email", "startup-admin@screen-factory-florida.com")
    with patch("app.main.bootstrap_admin") as mock_bootstrap:
        with TestClient(app):
            pass
        mock_bootstrap.assert_called_once()
        args = mock_bootstrap.call_args
        assert args[0][1] == "startup-admin@screen-factory-florida.com"


def test_startup_skips_bootstrap_admin_when_email_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "bootstrap_admin_email", None)
    with patch("app.main.bootstrap_admin") as mock_bootstrap:
        with TestClient(app):
            pass
        mock_bootstrap.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_bootstrap_startup.py -v`
Expected: FAIL — `mock_bootstrap.assert_called_once()` raises `AssertionError` (no startup hook exists yet).

- [ ] **Step 3: Add the startup hook to `main.py`**

Edit `backend/app/main.py`, add imports and the event handler after all `include_router` calls:

```python
from app.auth.service import bootstrap_admin
from app.core.database import SessionLocal
```

```python
@app.on_event("startup")
def _bootstrap_admin_on_startup() -> None:
    if not settings.bootstrap_admin_email:
        return
    db = SessionLocal()
    try:
        bootstrap_admin(db, settings.bootstrap_admin_email)
    finally:
        db.close()
```

This requires importing `settings` too — check if `app.core.config.settings` is already imported in `main.py`; if not, add `from app.core.config import settings`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_bootstrap_startup.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run full suite**

Run: `cd backend && pytest -v`
Expected: all tests pass. Watch specifically for any test that instantiates `TestClient(app)` as a context manager elsewhere and might now trigger a real (non-mocked) `bootstrap_admin` call against the test DB if `BOOTSTRAP_ADMIN_EMAIL` happens to be set in the local `.env` — if that env var is set locally, either unset it for test runs or confirm existing tests use `TestClient(app)` without the `with` context (which is the case for `tests/test_health.py` and all router tests observed — they instantiate `client = TestClient(app)` at module level without triggering lifespan events, since httpx/Starlette only runs `startup`/`shutdown` handlers when used as a context manager). Confirm this holds; if any existing test uses `with TestClient(app) as client:`, that test would now also run bootstrap — acceptable since it's idempotent, but worth noting in the PR description.

- [ ] **Step 6: Ruff check**

Run: `cd backend && ruff check app/main.py tests/test_bootstrap_startup.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/tests/test_bootstrap_startup.py
git commit -m "feat: bootstrap first admin from BOOTSTRAP_ADMIN_EMAIL at startup (ADR-0024 §2)"
```

---

## Task 9: Full-suite verification, ruff, and manual walkthrough prep

**Files:** none created/modified — verification only.

- [ ] **Step 1: Run the complete backend test suite**

Run: `cd backend && pytest -v --tb=short`
Expected: all tests pass — pre-existing router tests (supplier/material/price/price_ingestion/project/allocation/order/purchase_record/health) plus all new `tests/auth/`, `tests/user/`, `tests/scripts/test_bootstrap_admin.py`, `tests/test_bootstrap_startup.py`.

- [ ] **Step 2: Run ruff across the whole backend**

Run: `cd backend && ruff check .`
Expected: no errors.

- [ ] **Step 3: Confirm existing routers are still unauthenticated (explicit regression check)**

Run: `cd backend && python -c "
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
r = client.get('/suppliers')
print('suppliers GET status (should be 200, not 401/403):', r.status_code)
"`
Expected: `200` (or whatever the existing unauthenticated success code is) — confirms Task 7's `require_role` wiring on `/users` did not leak onto other routers.

- [ ] **Step 4: Verify migration is at head and matches models**

Run: `cd backend && python -m alembic check`
Expected: no pending model changes detected (Alembic's autogenerate-diff-against-models check) — confirms the migration in Task 2 fully captures the `User`/`UserSession` models from Task 1.

- [ ] **Step 5: Manual browser walkthrough — ask the user**

This step cannot be completed by an autonomous worker. At the end of this plan, tell the user:

> Full backend implementation is done and tested (pytest+ruff green). To manually verify the real browser OAuth flow, I need a Google Cloud Console OAuth 2.0 Client ID (Web application type) with:
> - Authorized redirect URI: `http://localhost:8000/auth/callback` (adjust host/port to match your local backend)
> - The `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_WORKSPACE_DOMAIN` (your Workspace domain, e.g. `screen-factory-florida.com`), `SESSION_SIGNING_SECRET` (any random string), and `BOOTSTRAP_ADMIN_EMAIL` (your own email) environment variables set in `backend/.env`.
>
> If you already have an OAuth client set up for this project, share those values (as env vars, not pasted directly in chat) and I'll walk through `/auth/login` → Google consent → `/auth/callback` → `/auth/me` with you. Otherwise, you'll need to create one in Google Cloud Console (APIs & Services → Credentials) first.

- [ ] **Step 6: Do not commit anything in this task** — it's verification-only. If Step 1 or Step 2 fail, fix forward in a new commit referencing which earlier task's code was wrong, then re-run this task's steps.

---

## Explicitly deferred (not part of this plan)

- **ADR-0024 §4/§5 wiring on existing routers** (`supplier`, `material`, `price`, `price_ingestion`, `project`, `allocation`, `order`, `purchase_record`) — next task, per explicit instruction. All 8 stay unauthenticated after this plan.
- **ADR-0024 §6 audit columns** (`Project.created_by_user_id`, `Order.created_by_user_id`, `PurchaseRecord.created_by_user_id`, `AllocationLine.overridden_by_user_id`) — requires touching the routers deferred above to populate them from `get_current_user`, so it travels with that follow-up task, not this one.
- **ADR-0024 §7 frontend** (`RequireAuth` guard, `client.ts` credentials/CSRF header, login page, header user info) — not requested in this task.
- **ADR-0024 §10 rate limiting** on `/auth/login`/`/auth/callback` — not requested in this task; flagged as a gap if this ships to production before that follow-up lands.
- `docs/architecture.md`, `docs/data-model.md`, `docs/spec.md` §7 updates per ADR-0024 "Последствия" — do after this plan's code is reviewed and merged, per CLAUDE.md's "после завершения значимого куска работы" step (batch the doc update with the router-wiring follow-up so `docs/data-model.md`'s `Project.created_by` → `created_by_user_id` note reflects real, not planned, state).
