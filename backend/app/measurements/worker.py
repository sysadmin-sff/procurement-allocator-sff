"""The measurements worker: python -m app.measurements.worker (ADR-0051 §1, §4).

One instance at a time, enforced with a Postgres advisory lock that the
backfill script also takes. SIGTERM rolls back the open transaction, releases
the lock and exits 0.
"""

import logging
import signal
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from app.measurements.amo_client import AmoAuthError, AmoClient
from app.measurements.config import MeasurementsConfigError, MeasurementsSettings
from app.measurements.models import MeasurementsSyncState
from app.measurements.reconcile import run_reconcile
from app.measurements.schedule import reconcile_due, reference_due
from app.measurements.sync import SyncContext, run_cycle, run_reference_cycle

logger = logging.getLogger("app.measurements.worker")

LOCK_KEY = 510051  # ADR-0051
LOCK_BUSY_EXIT = 3
CONFIG_ERROR_EXIT = 2
AUTH_RECHECK = timedelta(hours=1)
LOCK_BUSY_MESSAGE = "another measurements worker or backfill holds the advisory lock; exiting"


class StopRequested(BaseException):
    """Raised from the SIGTERM handler. Not an Exception, so stream handlers let it pass."""


def make_engine(url: str) -> Engine:
    """The worker's own small pool: one connection for the lock, one for work."""
    return create_engine(
        url,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"options": "-c statement_timeout=60000 -c lock_timeout=5000"},
    )


def acquire_lock(engine: Engine) -> Connection | None:
    connection = engine.connect()
    acquired = connection.execute(
        text("select pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}
    ).scalar()
    connection.commit()
    if not acquired:
        connection.close()
        return None
    return connection


def release_lock(connection: Connection | None) -> None:
    """Unlocks and discards the connection, so a pooled session cannot keep the lock."""
    if connection is None:
        return
    try:
        connection.execute(text("select pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
        connection.commit()
    except Exception:  # noqa: BLE001 - the invalidate below ends the session anyway
        logger.warning("advisory unlock failed; closing the connection instead")
    finally:
        connection.invalidate()
        connection.close()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Worker:
    def __init__(
        self,
        settings: MeasurementsSettings,
        engine: Engine,
        client: AmoClient,
        *,
        now: Callable[[], datetime] = _utcnow,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._settings = settings
        self._engine = engine
        self._client = client
        self._now = now
        self._sleep = sleep
        self._sessions = sessionmaker(bind=engine, autoflush=False)
        self._auth_blocked_until: datetime | None = None

    def run(self) -> int:
        lock = acquire_lock(self._engine)
        if lock is None:
            logger.error(LOCK_BUSY_MESSAGE)
            return LOCK_BUSY_EXIT

        previous = self._install_stop_handler()
        session = self._sessions()
        try:
            while True:
                self.tick(session)
                self._sleep(self._settings.poll_interval_seconds)
        except StopRequested:
            logger.info("measurements worker stopping on SIGTERM")
            return 0
        finally:
            try:
                session.rollback()
            finally:
                session.close()
                release_lock(lock)
                self._restore_stop_handler(previous)

    def tick(self, session: Session) -> None:
        now = self._now()
        if not self._settings.sync_enabled:
            self._heartbeat(session, "ok")
            session.commit()
            return
        if self._auth_blocked_until is not None and now < self._auth_blocked_until:
            self._heartbeat(session, "auth_failed")
            session.commit()
            return

        self._heartbeat(session, "running")
        session.commit()
        ctx = SyncContext(
            db=session,
            client=self._client,
            settings=self._settings,
            now=self._now,
            heartbeat=lambda: self._heartbeat(session, "running"),
        )
        try:
            if reference_due(self._last_attempt(session, "reference_custom_fields"), now):
                run_reference_cycle(ctx)
            run_cycle(ctx)
            zone = ZoneInfo(self._settings.timezone)
            if reconcile_due(self._last_attempt(session, "reconcile"), now, zone):
                run_reconcile(ctx)
        except AmoAuthError:
            self._auth_blocked_until = now + AUTH_RECHECK
            logger.error("amo rejected the token; polling paused until the next check")
            self._heartbeat(session, "auth_failed")
            session.commit()
            return
        self._auth_blocked_until = None
        self._heartbeat(session, "ok")
        session.commit()

    def _heartbeat(self, session: Session, status: str) -> None:
        state = session.get(MeasurementsSyncState, "worker")
        if state is None:
            state = MeasurementsSyncState(stream="worker", consecutive_failures=0, counters={})
            session.add(state)
        state.heartbeat_at = self._now()
        state.last_status = status

    @staticmethod
    def _last_attempt(session: Session, stream: str) -> datetime | None:
        state = session.get(MeasurementsSyncState, stream)
        return state.last_attempt_at if state else None

    @staticmethod
    def _install_stop_handler():
        if threading.current_thread() is not threading.main_thread():
            return None

        def stop(_signum, _frame):
            raise StopRequested

        return signal.signal(signal.SIGTERM, stop)

    @staticmethod
    def _restore_stop_handler(previous) -> None:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = MeasurementsSettings()
    try:
        settings.validate_for_worker()
    except MeasurementsConfigError as exc:
        logger.error("invalid measurements settings: %s", exc)
        return CONFIG_ERROR_EXIT

    from app.core.config import settings as core_settings  # noqa: PLC0415 - after validation

    engine = make_engine(core_settings.database_url)
    client = AmoClient(settings.amo_base_url, settings.amo_access_token)
    try:
        return Worker(settings, engine, client).run()
    finally:
        client.close()
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
