"""The one setting `main.py` reads while the module is off (ADR-0051, 2026-11-10).

Separate from `config.py` so that a malformed module setting cannot affect the
backend's startup while the flag is off.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class MeasurementsFlags(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MEASUREMENTS_", extra="ignore")

    enabled: bool = False
    """MEASUREMENTS_ENABLED: off means the routes do not exist and answer 404."""
