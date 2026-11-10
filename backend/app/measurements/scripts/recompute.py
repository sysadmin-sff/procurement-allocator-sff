"""Recomputes the derived rows of every lead (ADR-0053 §3). Dry-run by default.

    python -m app.measurements.scripts.recompute [--apply]

Reads only our database, never amo. Holds the same advisory lock as the worker
and the backfill. A dry-run computes in a read-only transaction and writes
nothing. Prints counters only, never client data.
"""

import argparse
import sys
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select, text, union
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.measurements.attribution_store import LeadDerived, compute_lead, write_lead
from app.measurements.config import MeasurementsConfigError, MeasurementsSettings
from app.measurements.models import (
    MeasurementsLead,
    MeasurementsResultAttribution,
    MeasurementsVisitOutcome,
)
from app.measurements.stale import count_stale_outcomes
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


def lead_ids(db: Session) -> list[int]:
    """Every known lead, and any lead that still has derived rows."""
    return sorted(
        db.scalars(
            union(
                select(MeasurementsLead.lead_id),
                select(MeasurementsVisitOutcome.lead_id),
                select(MeasurementsResultAttribution.lead_id),
            )
        ).all()
    )


def count(counters: Counter, derived: LeadDerived) -> None:
    counters["leads"] += 1
    counters["leads.skipped"] += int(derived.skipped)
    counters["attributions"] += len(derived.attribution.attributions)
    counters["other_exit"] += derived.outcomes.other_exit
    groups_with_duplicates = set()
    for row in derived.outcomes.rows:
        counters["rows"] += 1
        counters[f"rows.result_source.{row.result_source}"] += 1
        if row.funnel_outcome is not None:
            counters[f"rows.funnel_outcome.{row.funnel_outcome}"] += 1
        if row.is_duplicate:
            counters["duplicates"] += 1
            groups_with_duplicates.add(row.group_task_id)
            continue
        counters["groups"] += 1
        if row.result_source == "funnel":
            reason = f".{row.no_data_reason}" if row.no_data_reason else ""
            kind = derived.kinds[row.task_id]
            counters[f"groups.funnel.{kind}.{row.funnel_outcome}{reason}"] += 1
    counters["groups.with_duplicates"] += len(groups_with_duplicates)


_ALWAYS_PRINTED = (
    "leads",
    "leads.skipped",
    "attributions",
    "rows",
    "rows.result_source.funnel",
    "rows.result_source.site_visit",
    *(f"rows.funnel_outcome.{name}" for name in ("produced", "closed", "not_held", "no_data")),
    "groups",
    "groups.with_duplicates",
    "duplicates",
    "other_exit",
)


def run(db: Session, settings: MeasurementsSettings, *, apply: bool, now: datetime) -> Counter:
    counters: Counter = Counter({name: 0 for name in _ALWAYS_PRINTED})
    counters["stale_before"] = count_stale_outcomes(db)
    for lead_id in lead_ids(db):
        derived = compute_lead(db, lead_id, settings)
        count(counters, derived)
        if apply:
            write_lead(db, lead_id, derived, now)
            db.commit()
    if apply:
        counters["stale_after"] = count_stale_outcomes(db)
    return counters


def main(
    argv: list[str] | None = None,
    *,
    settings: MeasurementsSettings | None = None,
    engine: Engine | None = None,
    now: Callable[[], datetime] = _utcnow,
) -> int:
    args = _parse_args(argv)
    if settings is None:
        settings = MeasurementsSettings()
    try:
        settings.validate_for_worker(require_amo=False)
    except MeasurementsConfigError as exc:
        print(f"invalid measurements settings: {exc}", file=sys.stderr)
        return CONFIG_ERROR_EXIT
    owns_engine = engine is None
    if engine is None:
        from app.core.config import settings as core_settings  # noqa: PLC0415

        engine = make_engine(core_settings.database_url)

    lock = acquire_lock(engine)
    try:
        if lock is None:
            print(LOCK_BUSY_MESSAGE, file=sys.stderr)
            return LOCK_BUSY_EXIT
        with sessionmaker(bind=engine, autoflush=False)() as db:
            if not args.apply:
                db.execute(text("SET TRANSACTION READ ONLY"))
            try:
                counters = run(db, settings, apply=args.apply, now=now())
            finally:
                db.rollback()
        print(f"mode: {'apply' if args.apply else 'dry-run'}")
        for name in sorted(counters):
            print(f"{name}: {counters[name]}")
        print("APPLIED" if args.apply else "DRY-RUN: nothing written, re-run with --apply")
        return 0
    finally:
        release_lock(lock)
        if owns_engine:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
