"""When the worker runs reference sync and nightly reconciliation (ADR-0051 §4)."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

RECONCILE_AT = time(3, 30)
REFERENCE_EVERY = timedelta(hours=1)


def reconcile_due(
    last_attempt: datetime | None, now: datetime, zone: ZoneInfo, at: time = RECONCILE_AT
) -> bool:
    """True once per local day, at the first check at or after `at` local time.

    The target is built from the local date with zoneinfo, so a 23- or 25-hour
    day still has exactly one 03:30. A worker that was down at 03:30 catches up
    later the same day.
    """
    local_now = now.astimezone(zone)
    target = datetime.combine(local_now.date(), at, tzinfo=zone)
    if local_now < target:
        return False
    return last_attempt is None or last_attempt < target


def reference_due(
    last_attempt: datetime | None, now: datetime, every: timedelta = REFERENCE_EVERY
) -> bool:
    return last_attempt is None or now - last_attempt >= every
