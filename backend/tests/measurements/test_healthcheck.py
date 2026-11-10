"""Container healthcheck of measurements-worker."""

from datetime import timedelta

import pytest

from app.core.database import SessionLocal, engine
from app.measurements.config import MeasurementsSettings
from app.measurements.healthcheck import check
from app.measurements.models import MeasurementsSyncState
from tests.measurements.test_sync import NOW

POLL = timedelta(seconds=300)


def _beat(at) -> None:
    with SessionLocal() as db:
        db.merge(MeasurementsSyncState(stream="worker", heartbeat_at=at, consecutive_failures=0))
        db.commit()


def _settings(enabled=True) -> MeasurementsSettings:
    return MeasurementsSettings(_env_file=None, sync_enabled=enabled)


def test_disabled_sync_is_healthy_without_a_heartbeat(sync_tables_clean):
    healthy, message = check(engine, _settings(enabled=False), NOW)
    assert healthy
    assert "disabled" in message


def test_missing_heartbeat_is_unhealthy(sync_tables_clean):
    assert check(engine, _settings(), NOW) == (False, "unhealthy: no heartbeat yet")


@pytest.mark.parametrize(
    "age, healthy",
    [
        (timedelta(0), True),
        (3 * POLL, True),
        (3 * POLL + timedelta(seconds=1), False),
        (timedelta(hours=5), False),
    ],
)
def test_heartbeat_age_limit_is_three_poll_intervals(sync_tables_clean, age, healthy):
    _beat(NOW - age)
    assert check(engine, _settings(), NOW)[0] is healthy
