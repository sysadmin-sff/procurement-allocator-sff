"""Backfill of the measurements tables. Dry-run by default.

    python -m app.measurements.scripts.backfill [--apply]

Holds the same advisory lock as the worker, so the two never run together.
Prints counters only, never client data or the token.
"""

import argparse
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.measurements.amo_client import AmoClient
from app.measurements.backfill import apply, collect, summarize
from app.measurements.config import MeasurementsConfigError, MeasurementsSettings
from app.measurements.models import MeasurementsFieldValue
from app.measurements.sync import SyncContext
from app.measurements.worker import (
    CONFIG_ERROR_EXIT,
    LOCK_BUSY_EXIT,
    LOCK_BUSY_MESSAGE,
    acquire_lock,
    make_engine,
    release_lock,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    settings: MeasurementsSettings | None = None,
    engine: Engine | None = None,
    client: AmoClient | None = None,
    now: Callable[[], datetime] = _utcnow,
) -> int:
    args = _parse_args(argv)
    owns_resources = client is None
    if settings is None:
        settings = MeasurementsSettings()
    if client is None:
        try:
            settings.validate_for_worker()
        except MeasurementsConfigError as exc:
            print(f"invalid measurements settings: {exc}", file=sys.stderr)
            return CONFIG_ERROR_EXIT
        client = AmoClient(settings.amo_base_url, settings.amo_access_token)
    if engine is None:
        from app.core.config import settings as core_settings  # noqa: PLC0415

        engine = make_engine(core_settings.database_url)

    lock = acquire_lock(engine)
    if lock is None:
        print(LOCK_BUSY_MESSAGE, file=sys.stderr)
        return LOCK_BUSY_EXIT
    try:
        with engine.connect() as connection:
            mapping = dict(
                connection.execute(
                    select(MeasurementsFieldValue.enum_id, MeasurementsFieldValue.visit_occurred)
                ).all()
            )
            connection.rollback()

        started = now()
        collected = collect(client, settings)
        counters = summarize(collected, mapping, settings)

        print(f"mode: {'apply' if args.apply else 'dry-run'}")
        for name in sorted(counters):
            print(f"{name}: {counters[name]}")

        if not args.apply:
            print("DRY-RUN: nothing written, re-run with --apply")
            return 0
        with sessionmaker(bind=engine, autoflush=False)() as session:
            apply(
                collected,
                SyncContext(db=session, client=client, settings=settings, now=now),
                started,
            )
        print("APPLIED")
        return 0
    finally:
        release_lock(lock)
        if owns_resources:
            client.close()
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
