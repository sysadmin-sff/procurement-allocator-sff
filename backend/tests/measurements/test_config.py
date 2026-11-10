"""MeasurementsSettings against the ADR-0051 config table and 2026-11-10 change."""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.measurements.config import MeasurementsConfigError, MeasurementsSettings
from app.measurements.zone import TIMEZONE_NAME, ZONE

TOKEN = "super-secret-amo-token"
VALID = {
    "amo_access_token": TOKEN,
    "amo_base_url": "https://example.amocrm.com",
}


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MEASUREMENTS_"):
            monkeypatch.delenv(name)


def _settings(**overrides) -> MeasurementsSettings:
    return MeasurementsSettings(_env_file=None, **overrides)


def test_defaults_match_the_adr_table():
    settings = _settings()
    assert settings.enabled is False
    assert settings.sync_enabled is False
    assert settings.field_id == 784029
    assert settings.task_type_primary == 4410970
    assert settings.task_type_additional == 4410974
    assert settings.task_type_legacy == 2
    assert settings.measurer_map == {9861902: "Nazar", 14156562: "Matt Measurement"}
    assert settings.pipeline_measurements_id == 8740486
    assert settings.pipeline_sales_id == 8740490
    assert settings.cutover_at == datetime(2026, 11, 9, 5, tzinfo=timezone.utc)
    assert settings.legacy_meetings_until is None
    assert settings.excluded_lead_ids == frozenset()


def test_backend_can_build_settings_without_worker_values():
    settings = _settings()
    assert settings.amo_access_token is None
    assert settings.amo_base_url is None


def test_token_is_read_from_the_documented_variable(monkeypatch):
    monkeypatch.setenv("MEASUREMENTS_AMO_ACCESS_TOKEN", TOKEN)
    assert _settings().amo_access_token.get_secret_value() == TOKEN


def test_token_does_not_appear_in_repr_or_str():
    settings = _settings(**VALID)
    assert TOKEN not in repr(settings)
    assert TOKEN not in str(settings)


def test_valid_settings_pass_worker_validation():
    _settings(**VALID).validate_for_worker()


@pytest.mark.parametrize("missing", ["amo_access_token", "amo_base_url"])
def test_worker_validation_requires(missing):
    values = {key: value for key, value in VALID.items() if key != missing}
    with pytest.raises(MeasurementsConfigError, match=missing):
        _settings(sync_enabled=True, **values).validate_for_worker()


def test_disabled_sync_needs_no_token_or_base_url():
    _settings(sync_enabled=False).validate_for_worker()


def test_amo_access_can_be_required_regardless_of_the_flag():
    """The backfill always talks to amo."""
    with pytest.raises(MeasurementsConfigError, match="amo_access_token"):
        _settings(sync_enabled=False).validate_for_worker(require_amo=True)


def test_a_given_base_url_is_checked_even_when_sync_is_disabled():
    with pytest.raises(MeasurementsConfigError, match="amo_base_url"):
        _settings(sync_enabled=False, amo_base_url="http://evil.com").validate_for_worker()


def test_worker_validation_rejects_an_empty_token():
    with pytest.raises(MeasurementsConfigError, match="amo_access_token"):
        _settings(sync_enabled=True, **{**VALID, "amo_access_token": "  "}).validate_for_worker()


@pytest.mark.parametrize(
    "url",
    ["https://a.amocrm.com", "https://a.amocrm.ru", "https://amocrm.com", "https://A.AmoCRM.com/"],
)
def test_base_url_accepts_amo_domains(url):
    _settings(**{**VALID, "amo_base_url": url}).validate_for_worker()


@pytest.mark.parametrize(
    "url",
    [
        "http://a.amocrm.com",
        "https://evil.com",
        "https://amocrm.com.evil.com",
        "https://notamocrm.com",
        "https://a.amocrm.com@evil.com",
        "https://a.amocrm.org",
        "a.amocrm.com",
    ],
)
def test_base_url_rejects(url):
    with pytest.raises(MeasurementsConfigError, match="amo_base_url"):
        _settings(**{**VALID, "amo_base_url": url}).validate_for_worker()


def test_validation_errors_never_contain_the_token():
    settings = _settings(amo_access_token=TOKEN, amo_base_url="http://evil.com")
    with pytest.raises(MeasurementsConfigError) as exc_info:
        settings.validate_for_worker()
    assert TOKEN not in str(exc_info.value)


def test_measurer_map_must_be_one_to_one():
    settings = _settings(**VALID, measurer_map={1: "Nazar", 2: "Nazar"})
    with pytest.raises(MeasurementsConfigError, match="measurer_map"):
        settings.validate_for_worker()


def test_measurer_map_must_not_be_empty():
    with pytest.raises(MeasurementsConfigError, match="measurer_map"):
        _settings(**VALID, measurer_map={}).validate_for_worker()


def test_task_types_must_be_distinct():
    with pytest.raises(MeasurementsConfigError, match="task_type"):
        _settings(**VALID, task_type_additional=4410970).validate_for_worker()


def test_cutover_must_be_timezone_aware():
    with pytest.raises(MeasurementsConfigError, match="cutover_at"):
        _settings(**VALID, cutover_at=datetime(2026, 11, 9)).validate_for_worker()


def test_legacy_meetings_until_must_be_timezone_aware():
    with pytest.raises(MeasurementsConfigError, match="legacy_meetings_until"):
        _settings(**VALID, legacy_meetings_until=datetime(2026, 12, 1)).validate_for_worker()


def test_timezone_is_a_module_constant_not_a_setting(monkeypatch):
    """ADR-0053 §3: MeasurementsSettings.timezone is removed."""
    assert TIMEZONE_NAME == "America/New_York"
    assert ZONE == ZoneInfo("America/New_York")
    assert "timezone" not in MeasurementsSettings.model_fields
    monkeypatch.setenv("MEASUREMENTS_TIMEZONE", "Mars/Olympus")
    settings = _settings(**VALID)
    settings.validate_for_worker()
    assert not hasattr(settings, "timezone")


def test_all_problems_are_reported_together():
    with pytest.raises(MeasurementsConfigError) as exc_info:
        _settings(sync_enabled=True).validate_for_worker()
    assert "amo_access_token" in str(exc_info.value)
    assert "amo_base_url" in str(exc_info.value)
