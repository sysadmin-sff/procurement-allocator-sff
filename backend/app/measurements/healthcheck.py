"""Docker healthcheck of measurements-worker: python -m app.measurements.healthcheck.

Unhealthy when the worker heartbeat is older than three polling intervals.
Healthy when MEASUREMENTS_SYNC_ENABLED is false: the worker sleeps on purpose.
"""

import sys
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from app.measurements.config import MeasurementsSettings
from app.measurements.models import MeasurementsSyncState


def check(engine: Engine, settings: MeasurementsSettings, now: datetime) -> tuple[bool, str]:
    if not settings.sync_enabled:
        return True, "healthy: sync disabled"
    with engine.connect() as connection:
        heartbeat = connection.execute(
            select(MeasurementsSyncState.heartbeat_at).where(
                MeasurementsSyncState.stream == "worker"
            )
        ).scalar()
    if heartbeat is None:
        return False, "unhealthy: no heartbeat yet"
    age = now - heartbeat
    if age > timedelta(seconds=3 * settings.poll_interval_seconds):
        return False, f"unhealthy: heartbeat is {int(age.total_seconds())}s old"
    return True, f"healthy: heartbeat is {int(age.total_seconds())}s old"


def settings_for_check() -> MeasurementsSettings:
    """Unparseable settings are a config_error, not a dead worker: check its heartbeat."""
    try:
        return MeasurementsSettings()
    except ValidationError:
        return MeasurementsSettings.model_construct(sync_enabled=True)


def main() -> int:
    settings = settings_for_check()
    if not settings.sync_enabled:
        print("healthy: sync disabled")
        return 0
    from app.core.config import settings as core_settings  # noqa: PLC0415

    engine = create_engine(
        core_settings.database_url,
        poolclass=NullPool,
        connect_args={"options": "-c statement_timeout=5000", "connect_timeout": 5},
    )
    try:
        healthy, message = check(engine, settings, datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 - any failure is unhealthy
        healthy, message = False, f"unhealthy: {type(exc).__name__}"
    finally:
        engine.dispose()
    print(message)
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
