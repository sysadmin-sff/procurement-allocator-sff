"""03:30 New York reconciliation and hourly reference data (ADR-0051 §4)."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.measurements.schedule import reconcile_due, reference_due

NY = ZoneInfo("America/New_York")
TICK = timedelta(minutes=5)


def simulate(start_local: datetime, days: int) -> list[datetime]:
    """Ticks every 5 minutes in UTC and returns the local times reconciliation ran."""
    now = start_local.astimezone(timezone.utc)
    end = now + timedelta(days=days)
    last = None
    runs = []
    while now < end:
        if reconcile_due(last, now, NY):
            last = now
            runs.append(now.astimezone(NY))
        now += TICK
    return runs


@pytest.mark.parametrize(
    "start",
    [
        pytest.param(datetime(2027, 3, 13, tzinfo=NY), id="spring forward 2027-03-14"),
        pytest.param(datetime(2026, 10, 31, tzinfo=NY), id="fall back 2026-11-01"),
        pytest.param(datetime(2027, 11, 6, tzinfo=NY), id="fall back 2027-11-07"),
    ],
)
def test_exactly_once_per_local_day_across_dst(start):
    runs = simulate(start, days=3)
    per_day = Counter(run.date() for run in runs)
    assert sorted(per_day) == [start.date() + timedelta(days=offset) for offset in range(3)]
    assert set(per_day.values()) == {1}
    for run in runs:
        assert (run.hour, run.minute) == (3, 30)


def test_spring_forward_day_is_23_hours_and_still_runs_once():
    runs = simulate(datetime(2027, 3, 14, tzinfo=NY), days=1)
    assert len(runs) == 1
    day_start = datetime(2027, 3, 14, tzinfo=NY).astimezone(timezone.utc)
    day_end = datetime(2027, 3, 15, tzinfo=NY).astimezone(timezone.utc)
    assert day_end - day_start == timedelta(hours=23)


def test_fall_back_day_is_25_hours_and_still_runs_once():
    runs = simulate(datetime(2026, 11, 1, tzinfo=NY), days=1)
    assert len(runs) == 1
    day_start = datetime(2026, 11, 1, tzinfo=NY).astimezone(timezone.utc)
    day_end = datetime(2026, 11, 2, tzinfo=NY).astimezone(timezone.utc)
    assert day_end - day_start == timedelta(hours=25)


def test_not_due_before_0330():
    now = datetime(2027, 3, 10, 3, 29, tzinfo=NY).astimezone(timezone.utc)
    assert not reconcile_due(None, now, NY)


def test_first_start_after_0330_runs_once_that_day():
    now = datetime(2027, 3, 10, 14, tzinfo=NY).astimezone(timezone.utc)
    assert reconcile_due(None, now, NY)
    assert not reconcile_due(now, now + timedelta(hours=5), NY)


def test_a_late_worker_catches_up_on_the_same_day_only():
    last = datetime(2027, 3, 9, 3, 30, tzinfo=NY)
    assert reconcile_due(last, datetime(2027, 3, 10, 9, tzinfo=NY), NY)


def test_reference_is_due_hourly():
    now = datetime(2027, 3, 10, 12, tzinfo=timezone.utc)
    assert reference_due(None, now)
    assert not reference_due(now - timedelta(minutes=59), now)
    assert reference_due(now - timedelta(hours=1), now)
