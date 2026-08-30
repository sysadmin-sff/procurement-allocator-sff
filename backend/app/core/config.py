from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/procurement_allocator"

    openai_api_key: SecretStr | None = None
    """Secret, backend-only — never returned in any API response. See ADR-0018 п.1.
    SecretStr keeps the value out of repr()/str()/logs — call .get_secret_value()
    at the point of use (e.g. passing it to the OpenAI client)."""
    openai_order_response_model: str = "gpt-5.6-luna"
    """Provisional default pending accuracy verification on 3-5 real supplier
    documents — see ADR-0018 п.1. Config, not hardcoded, so the model can
    change without a code edit."""
    openai_embedding_model: str = "text-embedding-3-small"
    """1536-dim, $0.02/1M tokens as of summer 2026 — see ADR-0019 §1.
    Config, not hardcoded, same pattern as openai_order_response_model."""
    openai_price_ingestion_model: str = "gpt-5.6-luna"
    """Provisional default = current ADR-0018 vision model, pending accuracy
    verification on real supplier price lists — see ADR-0019 §3."""
    google_client_id: str | None = None
    """OAuth 2.0 client ID from Google Cloud Console. See ADR-0024 §8."""
    google_client_secret: SecretStr | None = None
    """Secret — never returned in any API response, never logged. See ADR-0024 §8.
    SecretStr — see openai_api_key docstring above for the pattern."""
    google_workspace_domain: str | None = None
    """Value the id_token's 'hd' claim must equal — see ADR-0024 §1 п.8."""
    session_signing_secret: SecretStr | None = None
    """Used only to sign the short-lived oauth_flow cookie (ADR-0024 §1 п.2) —
    UserSession/csrf_token are opaque DB-checked values, not signed separately.
    SecretStr — see openai_api_key docstring above for the pattern."""
    bootstrap_admin_email: str | None = None
    """See ADR-0024 §2 — bootstrap of the first admin at app startup."""
    frontend_url: str = "http://localhost:5173"
    """Base URL the OAuth callback redirects to after login (ADR-0024 §1 п.11)
    — must be an absolute URL, a relative one resolves against the backend
    host instead of the frontend and 404s."""
    cookie_secure: bool = True
    """Secure flag on auth cookies (ADR-0024 §9) — defaults True (fail-safe
    for prod/deploy). Set COOKIE_SECURE=false only for local HTTP dev, where
    the browser silently drops Secure cookies without HTTPS."""
    trusted_proxy_ip: str | None = None
    """Address of the reverse proxy that terminates HTTPS (ADR-0024 §9), as it
    appears on the TCP socket — an IP, not a hostname, since it is compared
    against request.client.host verbatim. X-Forwarded-For is honoured for rate
    limiting (ADR-0024 §10) only on requests whose peer is exactly this
    address; every other request is treated as a direct connection and the
    header is ignored. Unset (the default) means never trust the header —
    fail-safe for local dev, and in prod it degrades the per-employee limit
    into one bucket shared by the whole office rather than into a spoofable
    one. See docs/DEPLOYMENT.md."""


settings = Settings()
