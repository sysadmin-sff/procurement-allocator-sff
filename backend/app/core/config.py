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


settings = Settings()
