"""Per-IP rate limiting on the two OAuth endpoints — ADR-0024 §10.

Ten requests per minute per IP, sliding window, counted independently for
/auth/login and /auth/callback. The autouse _reset_rate_limits fixture in
conftest.py clears the counters around every test — the limiter is
process-global, so these tests would otherwise poison each other.
"""

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import settings
from app.core.rate_limit import AUTH_RATE_LIMIT_PER_MINUTE, FORWARDED_FOR_HEADER
from app.main import app

client = TestClient(app, follow_redirects=False)

REDIRECT_STATUSES = (302, 307)
CALLBACK_QUERY = {"code": "irrelevant", "state": "irrelevant"}
TRUSTED_PROXY_IP = "10.0.0.9"


def _configure_settings(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", SecretStr("test-client-secret"))
    monkeypatch.setattr(settings, "google_workspace_domain", "screen-factory-florida.com")


def _behind_trusted_proxy(monkeypatch) -> TestClient:
    """A client whose TCP peer is the configured reverse proxy — the only
    position from which X-Forwarded-For is believed."""
    monkeypatch.setattr(settings, "trusted_proxy_ip", TRUSTED_PROXY_IP)
    return TestClient(app, follow_redirects=False, client=(TRUSTED_PROXY_IP, 44300))


def test_login_returns_429_on_the_request_after_the_limit(monkeypatch):
    _configure_settings(monkeypatch)

    for i in range(AUTH_RATE_LIMIT_PER_MINUTE):
        response = client.get("/auth/login")
        assert response.status_code in REDIRECT_STATUSES, f"request {i + 1} should still pass"

    blocked = client.get("/auth/login")

    assert blocked.status_code == 429


def test_callback_returns_429_on_the_request_after_the_limit(monkeypatch):
    _configure_settings(monkeypatch)
    client.cookies.clear()

    for i in range(AUTH_RATE_LIMIT_PER_MINUTE):
        response = client.get("/auth/callback", params=CALLBACK_QUERY)
        # 400 "OAuth flow expired or missing" means the handler actually ran
        # and the limiter let the request through — that is what makes the
        # 429 below a real limiter hit rather than any old rejection.
        assert response.status_code == 400, f"request {i + 1} should still reach the handler"

    blocked = client.get("/auth/callback", params=CALLBACK_QUERY)

    assert blocked.status_code == 429


def test_login_and_callback_have_independent_budgets(monkeypatch):
    """A counter shared across both paths would break a legitimate login:
    retry /auth/login a few times and you could no longer reach
    /auth/callback to finish the flow. ADR-0024 §10 scopes the limit to each
    of the two paths."""
    _configure_settings(monkeypatch)
    client.cookies.clear()

    for _ in range(AUTH_RATE_LIMIT_PER_MINUTE):
        client.get("/auth/login")
    assert client.get("/auth/login").status_code == 429

    client.cookies.clear()
    callback = client.get("/auth/callback", params=CALLBACK_QUERY)

    assert callback.status_code == 400, "callback must not spend the login budget"


def test_limit_is_per_ip_not_global(monkeypatch):
    """One abusive client must not lock every other employee out of logging in."""
    _configure_settings(monkeypatch)
    noisy = TestClient(app, follow_redirects=False, client=("203.0.113.10", 51000))
    innocent = TestClient(app, follow_redirects=False, client=("203.0.113.11", 51000))

    for _ in range(AUTH_RATE_LIMIT_PER_MINUTE):
        noisy.get("/auth/login")
    assert noisy.get("/auth/login").status_code == 429

    assert innocent.get("/auth/login").status_code in REDIRECT_STATUSES


def test_rate_limited_response_uses_the_app_error_shape(monkeypatch):
    """429 carries {"detail": ...} like every HTTPException in this app, not
    slowapi's default {"error": ...}, so the frontend parses one shape."""
    _configure_settings(monkeypatch)

    for _ in range(AUTH_RATE_LIMIT_PER_MINUTE + 1):
        response = client.get("/auth/login")

    assert response.status_code == 429
    assert response.json() == {"detail": "Too many requests, please try again later."}
    assert response.headers["retry-after"] == "60"


def test_forwarded_for_budgets_are_per_client_ip(monkeypatch):
    """Two requests that differ only in X-Forwarded-For must not share a
    budget. Behind the HTTPS proxy that ADR-0024 §9 makes mandatory every
    request arrives from the same socket address, so keying on that address
    would put the whole office in one bucket — the tenth login of the morning
    would lock out everyone else."""
    _configure_settings(monkeypatch)
    proxied = _behind_trusted_proxy(monkeypatch)
    noisy = {FORWARDED_FOR_HEADER: "203.0.113.1"}

    for i in range(AUTH_RATE_LIMIT_PER_MINUTE):
        response = proxied.get("/auth/login", headers=noisy)
        assert response.status_code in REDIRECT_STATUSES, f"request {i + 1} should still pass"

    assert proxied.get("/auth/login", headers=noisy).status_code == 429

    innocent = proxied.get("/auth/login", headers={FORWARDED_FOR_HEADER: "203.0.113.2"})

    assert innocent.status_code in REDIRECT_STATUSES, (
        "a different forwarded client IP must keep its own budget, "
        "even though both requests share one socket address"
    )


def test_forwarded_for_counts_the_leftmost_address(monkeypatch):
    """The client is the first entry; everything after it is the proxy chain
    the request passed through. Counting a proxy hop instead would merge every
    employee behind that hop into one budget."""
    _configure_settings(monkeypatch)
    proxied = _behind_trusted_proxy(monkeypatch)
    exhausted = {FORWARDED_FOR_HEADER: "203.0.113.5, 10.0.0.1, 10.0.0.2"}

    for _ in range(AUTH_RATE_LIMIT_PER_MINUTE):
        proxied.get("/auth/login", headers=exhausted)
    assert proxied.get("/auth/login", headers=exhausted).status_code == 429

    same_chain_other_client = proxied.get(
        "/auth/login", headers={FORWARDED_FOR_HEADER: "203.0.113.6, 10.0.0.1, 10.0.0.2"}
    )

    assert same_chain_other_client.status_code in REDIRECT_STATUSES


def test_forwarded_for_ignored_when_peer_is_not_the_trusted_proxy(monkeypatch):
    """A caller reaching the app directly is talking as itself, so its header
    is worthless. Each request below carries a *different* X-Forwarded-For:
    if the header were honoured every one would open its own budget and no
    429 could ever occur. The 429 is only reachable by ignoring the header
    and counting the socket address."""
    _configure_settings(monkeypatch)
    monkeypatch.setattr(settings, "trusted_proxy_ip", TRUSTED_PROXY_IP)
    direct = TestClient(app, follow_redirects=False, client=("198.51.100.77", 44300))

    for i in range(AUTH_RATE_LIMIT_PER_MINUTE):
        response = direct.get("/auth/login", headers={FORWARDED_FOR_HEADER: f"203.0.113.{i}"})
        assert response.status_code in REDIRECT_STATUSES, f"request {i + 1} should still pass"

    blocked = direct.get("/auth/login", headers={FORWARDED_FOR_HEADER: "203.0.113.200"})

    assert blocked.status_code == 429, "a spoofed header must not mint a fresh budget"


def test_forwarded_for_ignored_when_no_trusted_proxy_is_configured(monkeypatch):
    """The default is to trust nobody. Same construction as the test above —
    a varying header that would defeat the limit if it were believed."""
    _configure_settings(monkeypatch)
    monkeypatch.setattr(settings, "trusted_proxy_ip", None)
    direct = TestClient(app, follow_redirects=False, client=("198.51.100.88", 44300))

    for _ in range(AUTH_RATE_LIMIT_PER_MINUTE):
        direct.get("/auth/login", headers={FORWARDED_FOR_HEADER: "203.0.113.9"})

    blocked = direct.get("/auth/login", headers={FORWARDED_FOR_HEADER: "203.0.113.10"})

    assert blocked.status_code == 429


def test_without_forwarded_for_the_socket_address_still_limits(monkeypatch):
    """Local development runs with no proxy in front, so the fallback path has
    to enforce the limit on its own."""
    _configure_settings(monkeypatch)
    direct = TestClient(app, follow_redirects=False, client=("198.51.100.20", 40000))

    for _ in range(AUTH_RATE_LIMIT_PER_MINUTE):
        direct.get("/auth/login")

    assert direct.get("/auth/login").status_code == 429


def test_unparseable_forwarded_for_falls_back_to_the_socket_address(monkeypatch):
    """Even from the trusted proxy, a header that is not an IP must not become
    a key of its own: varying the garbage per request would mint a fresh
    budget every time and the limit would never bite."""
    _configure_settings(monkeypatch)
    proxied = _behind_trusted_proxy(monkeypatch)

    for i in range(AUTH_RATE_LIMIT_PER_MINUTE):
        proxied.get("/auth/login", headers={FORWARDED_FOR_HEADER: f"not-an-ip-{i}"})

    blocked = proxied.get("/auth/login", headers={FORWARDED_FOR_HEADER: "not-an-ip-final"})

    assert blocked.status_code == 429
