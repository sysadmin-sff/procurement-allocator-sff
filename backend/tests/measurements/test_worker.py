"""The worker process (ADR-0051 §1, §4): lock, schedule, stop, failures."""

import logging
import signal
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.cookies import SESSION_COOKIE
from app.core.database import SessionLocal
from app.main import app as main_app
from app.measurements.config import MeasurementsSettings
from app.measurements.models import MeasurementsSyncState, MeasurementsVisit
from app.measurements.worker import (
    LOCK_BUSY_EXIT,
    Worker,
    acquire_lock,
    main,
    make_engine,
    release_lock,
)
from tests.measurements.test_sync import NOW, TASK, Env, lead_snapshot, make_task

TEST_URL_ENV = "DATABASE_URL"


@pytest.fixture
def worker_engine():
    import os

    engine = make_engine(os.environ[TEST_URL_ENV])
    yield engine
    engine.dispose()


@pytest.fixture
def env(sync_tables_clean):
    with SessionLocal() as db:
        environment = Env(db)
        environment.settings = MeasurementsSettings(_env_file=None, sync_enabled=True)
        yield environment


class Clock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now


def make_worker(env, engine, clock, sleep=None) -> Worker:
    return Worker(
        env.settings,
        engine,
        env.client,
        now=clock,
        sleep=sleep or (lambda seconds: None),
    )


def stop_after(ticks: int, clock: Clock):
    calls = {"count": 0}

    def sleep(seconds: float) -> None:
        calls["count"] += 1
        clock.now += timedelta(seconds=seconds)
        if calls["count"] >= ticks:
            signal.raise_signal(signal.SIGTERM)

    return sleep


def worker_state(env) -> MeasurementsSyncState:
    return env.state("worker")


# --- engine and lock


def test_engine_is_small_and_has_timeouts(worker_engine):
    assert worker_engine.pool.size() == 2
    assert worker_engine.pool._max_overflow == 0
    with worker_engine.connect() as connection:
        assert connection.execute(text("show statement_timeout")).scalar() == "1min"
        assert connection.execute(text("show lock_timeout")).scalar() == "5s"


def test_second_worker_exits_with_a_clear_message(env, worker_engine, caplog):
    holder = acquire_lock(worker_engine)
    try:
        caplog.set_level(logging.ERROR)
        code = make_worker(env, worker_engine, Clock(NOW)).run()
    finally:
        release_lock(holder)
    assert code == LOCK_BUSY_EXIT
    assert "another measurements worker or backfill" in caplog.text


def test_only_one_lock_holder_at_a_time(worker_engine):
    first = acquire_lock(worker_engine)
    try:
        assert first is not None
        assert acquire_lock(worker_engine) is None
    finally:
        release_lock(first)
    second = acquire_lock(worker_engine)
    assert second is not None
    release_lock(second)


# --- stopping


def test_sigterm_exits_zero_and_frees_the_lock_at_once(env, worker_engine):
    clock = Clock(NOW)
    code = make_worker(env, worker_engine, clock, stop_after(2, clock)).run()
    assert code == 0
    second = acquire_lock(worker_engine)
    assert second is not None
    release_lock(second)


def test_sigterm_during_a_page_rolls_its_writes_back(env, worker_engine):
    env.amo.add_task(make_task())
    env.amo.leads[777001] = lead_snapshot()

    def stop_on_history(request):
        if request.url.params.get("filter[entity]") == "task":
            signal.raise_signal(signal.SIGTERM)
        return None

    env.amo.fail_when = stop_on_history
    code = make_worker(env, worker_engine, Clock(NOW)).run()
    assert code == 0
    env.db.expire_all()
    assert env.db.get(MeasurementsVisit, TASK) is None
    second = acquire_lock(worker_engine)
    assert second is not None
    release_lock(second)


def test_previous_sigterm_handler_is_restored(env, worker_engine):
    before = signal.getsignal(signal.SIGTERM)
    clock = Clock(NOW)
    make_worker(env, worker_engine, clock, stop_after(1, clock)).run()
    assert signal.getsignal(signal.SIGTERM) == before


# --- ticks


def test_tick_writes_a_heartbeat(env, worker_engine):
    clock = Clock(NOW)
    make_worker(env, worker_engine, clock, stop_after(1, clock)).run()
    assert worker_state(env).heartbeat_at == NOW


def test_disabled_sync_only_heartbeats(env, worker_engine):
    env.settings = MeasurementsSettings(_env_file=None, sync_enabled=False)
    clock = Clock(NOW)
    make_worker(env, worker_engine, clock, stop_after(2, clock)).run()
    assert env.amo.requests == []
    assert worker_state(env).heartbeat_at == NOW + timedelta(minutes=5)


def test_reference_runs_hourly_and_reconcile_once_a_day(env, worker_engine):
    # 2026-11-10 07:00 UTC is 02:00 New York: reconciliation is due at 08:30 UTC.
    clock = Clock(datetime(2026, 11, 10, 7, tzinfo=timezone.utc))
    make_worker(env, worker_engine, clock, stop_after(36, clock)).run()  # 3 hours
    reference_calls = env.amo.calls_to("/leads/custom_fields")
    assert len(reference_calls) == 3
    listing = [
        call
        for call in env.amo.calls_to("/tasks")
        if "filter[updated_at][from]" not in call.url.params
    ]
    assert len(listing) == 3  # one full list per visit task type, one reconciliation
    assert env.state("reconcile").last_status == "ok"


def test_auth_failure_stops_polling_until_the_rare_check(env, worker_engine):
    env.amo.fail_when = lambda request: httpx.Response(401)
    clock = Clock(NOW)
    make_worker(env, worker_engine, clock, stop_after(6, clock)).run()  # 30 minutes
    assert len(env.amo.requests) == 1
    assert worker_state(env).last_status == "auth_failed"
    assert worker_state(env).heartbeat_at == NOW + timedelta(minutes=25)


def test_auth_is_checked_again_after_an_hour(env, worker_engine):
    env.amo.fail_when = lambda request: httpx.Response(401)
    clock = Clock(NOW)
    make_worker(env, worker_engine, clock, stop_after(13, clock)).run()  # 65 minutes
    assert len(env.amo.requests) == 2


def test_main_app_keeps_working_and_shows_the_failure(
    env, worker_engine, enabled_app, make_user, make_session
):
    env.amo.fail_when = lambda request: httpx.Response(401)
    clock = Clock(NOW)
    make_worker(env, worker_engine, clock, stop_after(1, clock)).run()

    assert TestClient(main_app).get("/health").status_code == 200
    client = TestClient(enabled_app)
    client.cookies.set(SESSION_COOKIE, str(make_session(make_user(role="admin")).id))
    streams = {row["stream"]: row for row in client.get("/measurements/status").json()["streams"]}
    assert streams["reference_custom_fields"]["last_status"] == "auth_failed"
    assert streams["reference_custom_fields"]["last_http_status"] == 401


def test_main_refuses_to_start_with_invalid_settings(monkeypatch, caplog):
    for name in ("MEASUREMENTS_AMO_ACCESS_TOKEN", "MEASUREMENTS_AMO_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir("/")
    caplog.set_level(logging.ERROR)
    assert main([]) == 2
    assert "amo_access_token" in caplog.text
