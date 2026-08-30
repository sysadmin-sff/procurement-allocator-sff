"""In-memory per-IP rate limiting for the OAuth endpoints — see ADR-0024 §10.

Sliding window ("moving-window" in `limits` terms), 10 requests/minute per
client IP, counted **independently per URL path** so exhausting `/auth/login`
never locks out `/auth/callback` mid-flow — a shared counter would break a
legit login the moment someone retried the first leg a few times.

Deliberately no Redis: ADR-0024 §10 asks for the simplest thing proportional
to the scale (one backend process, tens of employees). The counters live in
this process's memory and reset on restart, which is acceptable for abuse
damping — it is not a security boundary.

Accepted gap: the limit is checked inside the endpoint, after FastAPI has
validated the request, so a call rejected at validation (e.g. /auth/callback
with no code/state at all) never reaches the counter. That path is cheap —
it makes no outbound call to Google — so the expensive work stays covered.
"""

import ipaddress
import logging

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

logger = logging.getLogger(__name__)

AUTH_RATE_LIMIT_PER_MINUTE = 10
"""Conservative limit from ADR-0024 §10. This guards the OAuth flow against
abuse (each /auth/callback hit costs an outbound token exchange to Google),
not passwords against brute force — there is no password. Tightening it is
explicitly out of scope of that ADR."""

AUTH_RATE_LIMIT = f"{AUTH_RATE_LIMIT_PER_MINUTE}/minute"

FORWARDED_FOR_HEADER = "X-Forwarded-For"


def _parses_as_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def client_ip(request: Request) -> str:
    """The address the limit is counted against.

    HTTPS is terminated at a reverse proxy (ADR-0024 §9), so
    `request.client.host` is the proxy's own address — a single value for the
    entire office. Keying on it would turn a per-employee limit into one
    shared bucket that the tenth login of the morning empties for everybody.
    `X-Forwarded-For` carries the real client as its leftmost entry; the rest
    of the list is the proxy chain the request travelled through.

    The header is believed **only** when the TCP peer is exactly
    `settings.trusted_proxy_ip`. Anyone reaching this app directly — the
    backend port left exposed, a container on the same network, a future
    deployment that drops the proxy — is talking to us as themselves, so
    their header is ignored and the socket address is used, the same
    fallback as a request with no header at all. Without this check a caller
    could pick any address it liked: spend a colleague's budget, or rotate
    the header and never be limited. That guarantee then rests on code, not
    on someone remembering the right nginx directive a year from now.

    Unset `trusted_proxy_ip` means no peer is ever trusted. The limit still
    works, it just counts the proxy as one client — over-restrictive rather
    than bypassable. See docs/DEPLOYMENT.md for the deployment contract this
    depends on (the proxy must *replace* X-Forwarded-For, not append to it).
    """
    peer = get_remote_address(request)
    trusted_proxy = settings.trusted_proxy_ip
    if not trusted_proxy or peer != trusted_proxy:
        return peer

    forwarded_for = request.headers.get(FORWARDED_FOR_HEADER)
    if forwarded_for:
        candidate = forwarded_for.split(",")[0].strip()
        # Junk must not become a key: the key space is this process's memory,
        # and an unvalidated header is unbounded. Falling back also keeps a
        # varying garbage header from minting a fresh budget per request.
        if _parses_as_ip(candidate):
            return candidate
    return peer


limiter = Limiter(
    key_func=client_ip,
    strategy="moving-window",
    storage_uri="memory://",
    key_style="url",
)
"""key_style="url" makes the storage key (client IP, request path) — that is
what gives each of the two paths its own budget rather than one shared one."""


def rate_limit_exceeded_handler(request: Request, exc: Exception) -> Response:
    """429 in this app's error shape ({"detail": ...}, same as every
    HTTPException raised elsewhere) rather than slowapi's default
    {"error": ...}, so clients parse one format. The message is deliberately
    generic — it does not confirm whether the path exists or was reached."""
    logger.warning(
        "Rate limit exceeded: path=%s client=%s",
        request.url.path,
        client_ip(request),
    )
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests, please try again later."},
        headers={"Retry-After": "60"},
    )


def reset_rate_limits() -> None:
    """Clear every counter. Test-support only — the limiter is process-global,
    so without this one test's requests spend the next test's budget and test
    ordering decides who gets a surprise 429."""
    limiter.reset()
