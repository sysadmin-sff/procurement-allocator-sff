"""Settings of the measurements worker (ADR-0051 §3, §5, 2026-11-10 change)."""

from datetime import datetime
from urllib.parse import urlsplit

from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from app.measurements.flags import MeasurementsFlags
from app.measurements.zone import ZONE

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
    pipeline_qualification_id: int = 8740374
    """Qualification: a visit whose lead leaves Measurements for it was not held (ADR-0053 §3)."""
    cutover_at: datetime = datetime(2026, 11, 9, tzinfo=ZONE)
    legacy_meetings_until: datetime | None = None
    """Unset while the transition period is open."""
    excluded_lead_ids: frozenset[int] = frozenset()
    poll_interval_seconds: int = 300
    """ADR-0051 §4: polling every 5 minutes."""

    @property
    def field_event_type(self) -> str:
        return f"custom_field_{self.field_id}_value_changed"

    def validate_for_worker(self, *, require_amo: bool | None = None) -> None:
        """Raises listing every invalid setting at once.

        The token and base URL are required only when amo is read: when sync is
        enabled, or always with `require_amo=True` (the backfill). A base URL that
        is given is checked either way.
        """
        problems: list[str] = []
        needs_amo = self.sync_enabled if require_amo is None else require_amo

        token = self.amo_access_token
        if needs_amo and (token is None or not token.get_secret_value().strip()):
            problems.append("amo_access_token is required")
        if self.amo_base_url is None:
            if needs_amo:
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

        if problems:
            raise MeasurementsConfigError("; ".join(problems))
