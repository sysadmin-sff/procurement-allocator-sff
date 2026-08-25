from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/procurement_allocator"

    openai_api_key: str | None = None
    """Secret, backend-only — never returned in any API response. See ADR-0018 п.1."""
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


settings = Settings()
