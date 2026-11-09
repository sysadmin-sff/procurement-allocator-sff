"""Settings of the measurements worker (ADR-0051 §3, §5, 2026-11-10 change)."""

from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from app.measurements.flags import MeasurementsFlags

_NEW_YORK = "America/New_York"
_AMO_DOMAINS = ("amocrm.ru", "amocrm.com")


class MeasurementsConfigError(ValueError):
    """Names the invalid settings. The message never holds their values."""


def _is_amo_url(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return (
        parts.scheme == "https"
        and parts.username is None
        and any(host == domain or host.endswith(f".{domain}") for domain in _AMO_DOMAINS)
    )


def _is_naive(value: datetime) -> bool:
    return value.utcoffset() is None


def _zone_exists(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


class MeasurementsSettings(MeasurementsFlags):
    """Built only by the worker and its scripts, so the backend never holds the token."""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.measurements"), env_prefix="MEASUREMENTS_", extra="ignore"
    )

    sync_enabled: bool = False
    amo_access_token: SecretStr | None = None
    amo_base_url: str | None = None

    field_id: int = 784029
    task_type_primary: int = 4410970
    task_type_additional: int = 4410974
    task_type_legacy: int = 2
    measurer_map: dict[int, str] = {9861902: "Nazar", 14156562: "Matt Measurement"}
    """amo account id -> measurer key, one to one. A new account is one more entry."""
    pipeline_measurements_id: int = 8740486
    pipeline_sales_id: int = 8740490
    cutover_at: datetime = datetime(2026, 11, 9, tzinfo=ZoneInfo(_NEW_YORK))
    legacy_meetings_until: datetime | None = None
    """Unset while the transition period is open."""
    timezone: str = _NEW_YORK
    excluded_lead_ids: frozenset[int] = frozenset()

    def validate_for_worker(self) -> None:
        """Raises at worker start, listing every invalid setting at once."""
        problems: list[str] = []

        token = self.amo_access_token
        if token is None or not token.get_secret_value().strip():
            problems.append("amo_access_token is required")
        if self.amo_base_url is None:
            problems.append("amo_base_url is required")
        elif not _is_amo_url(self.amo_base_url):
            problems.append("amo_base_url must be https on amocrm.ru or amocrm.com")

        if not self.measurer_map:
            problems.append("measurer_map must not be empty")
        elif len(set(self.measurer_map.values())) != len(self.measurer_map):
            problems.append("measurer_map must be one to one")

        task_types = (self.task_type_primary, self.task_type_additional, self.task_type_legacy)
        if len(set(task_types)) != len(task_types):
            problems.append("task_type_* ids must be distinct")

        if _is_naive(self.cutover_at):
            problems.append("cutover_at must be timezone-aware")
        if self.legacy_meetings_until is not None and _is_naive(self.legacy_meetings_until):
            problems.append("legacy_meetings_until must be timezone-aware")
        if not _zone_exists(self.timezone):
            problems.append("timezone is not a known zone")

        if problems:
            raise MeasurementsConfigError("; ".join(problems))
