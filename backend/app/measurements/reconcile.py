"""Nightly reconciliation (ADR-0051 §4, 2026-11-10 change).

Order matters: everything is read and planned first, the 5% fuse is checked,
and only then is anything written. The DB-only reclassification of `kind`
still applies when amo cannot be read.
"""

from collections import Counter
from datetime import datetime

from sqlalchemy import func, select, update

from app.measurements.amo_client import AmoError
from app.measurements.attribution_store import recompute_lead
from app.measurements.classification import classify_kind
from app.measurements.models import MeasurementsLead, MeasurementsVisit
from app.measurements.sync import (
    ReconcileAborted,
    SyncContext,
    _as_datetime,
    _commit,
    _ingest_task,
    _run_stream,
    _upsert_lead,
)

_SAFETY_SHARE = 0.05
_LEAD_BATCH = 50
_WRITE_BATCH = 100


def _too_many(removals: int, total: int) -> bool:
    return removals > 0 and removals > _SAFETY_SHARE * total


def _plan_reclassification(ctx: SyncContext) -> tuple[set[int], set[int]]:
    """Legacy rows whose `kind` changes under the current settings, from our data only."""
    settings = ctx.settings
    rows = ctx.db.execute(
        select(
            MeasurementsVisit.task_id,
            MeasurementsVisit.task_type_id,
            MeasurementsVisit.responsible_amo_user_id,
            MeasurementsVisit.scheduled_at,
            MeasurementsVisit.amo_created_at,
            MeasurementsVisit.deleted_at,
            MeasurementsVisit.deleted_reason,
        ).where(MeasurementsVisit.task_type_id == settings.task_type_legacy)
    ).all()
    retype, restore = set(), set()
    for row in rows:
        kind = classify_kind(
            settings,
            row.task_type_id,
            row.responsible_amo_user_id,
            row.scheduled_at,
            row.amo_created_at,
        )
        if kind is None and row.deleted_at is None:
            retype.add(row.task_id)
        elif kind == "legacy" and row.deleted_reason == "retyped":
            restore.add(row.task_id)
    return retype, restore


def _read_amo(ctx: SyncContext, known_leads: list[int]) -> tuple[dict[int, dict], dict[int, dict]]:
    settings = ctx.settings
    listed: dict[int, dict] = {}
    for task_type in (
        settings.task_type_primary,
        settings.task_type_additional,
        settings.task_type_legacy,
    ):
        for batch in ctx.client.iter_pages("/tasks", "tasks", [("filter[task_type][]", task_type)]):
            for raw in batch:
                listed[raw["id"]] = raw
    snapshots: dict[int, dict] = {}
    for start in range(0, len(known_leads), _LEAD_BATCH):
        params = [("filter[id][]", lead_id) for lead_id in known_leads[start : start + _LEAD_BATCH]]
        for batch in ctx.client.iter_pages("/leads", "leads", params):
            for raw in batch:
                snapshots[raw["id"]] = raw
    return listed, snapshots


def _listed_kind(ctx: SyncContext, raw: dict) -> str | None:
    return classify_kind(
        ctx.settings,
        raw["task_type_id"],
        raw["responsible_user_id"],
        _as_datetime(raw["complete_till"]),
        _as_datetime(raw["created_at"]),
    )


def _recompute_all(ctx: SyncContext, counters: Counter, now: datetime) -> None:
    for lead_id in ctx.db.scalars(select(MeasurementsLead.lead_id)).all():
        recompute_lead(ctx.db, lead_id, ctx.settings, now)
        _commit(ctx)
        counters["recomputed"] += 1


def _reconcile(ctx: SyncContext, counters: Counter) -> None:
    db = ctx.db
    active = set(
        db.scalars(
            select(MeasurementsVisit.task_id).where(MeasurementsVisit.deleted_at.is_(None))
        ).all()
    )
    known_leads = sorted(
        db.scalars(
            select(MeasurementsLead.lead_id).where(MeasurementsLead.deleted_at.is_(None))
        ).all()
    )
    db_retype, db_restore = _plan_reclassification(ctx)

    amo_error: AmoError | None = None
    listed: dict[int, dict] | None = None
    snapshots: dict[int, dict] = {}
    try:
        listed, snapshots = _read_amo(ctx, known_leads)
    except AmoError as exc:
        amo_error = exc

    # Only removals implied by amo's answers count toward the fuse. Changes that
    # follow from our own settings (2026-11-10 change) always apply.
    visit_removals: set[int] = set()
    missing: set[int] = set()
    lead_removals: set[int] = set()
    if listed is not None:
        missing = active - set(listed)
        visit_removals |= missing
        visit_removals |= {
            task_id
            for task_id, raw in listed.items()
            if task_id in active and _listed_kind(ctx, raw) is None
        } - db_retype
        lead_removals = set(known_leads) - set(snapshots)

    counters["active_visits"] = len(active)
    counters["visit_removals"] = len(visit_removals)
    counters["known_leads"] = len(known_leads)
    counters["lead_removals"] = len(lead_removals)

    now = ctx.now()
    if db_retype:
        db.execute(
            update(MeasurementsVisit)
            .where(MeasurementsVisit.task_id.in_(db_retype))
            .values(deleted_at=now, deleted_reason="retyped", synced_at=now)
        )
    if db_restore:
        db.execute(
            update(MeasurementsVisit)
            .where(MeasurementsVisit.task_id.in_(db_restore))
            .values(deleted_at=None, deleted_reason=None, synced_at=now)
        )
    counters["reclassified_retyped"] = len(db_retype)
    counters["reclassified_restored"] = len(db_restore)
    _commit(ctx)

    if _too_many(len(visit_removals), len(active)) or _too_many(
        len(lead_removals), len(known_leads)
    ):
        # ADR-0053 §3: recomputing reads only our data, which the fuse does not
        # protect, so config and rule changes still reach every lead.
        _recompute_all(ctx, counters, now)
        raise ReconcileAborted("amo answers would remove more than 5% of rows")

    if listed is not None:
        listing_counters: Counter = Counter()
        for number, raw in enumerate(listed.values(), start=1):
            _ingest_task(ctx, raw, listing_counters)
            if number % _WRITE_BATCH == 0:
                _commit(ctx)
        counters["post_cutover_meeting_ignored"] = listing_counters["post_cutover_meeting_ignored"]
        _commit(ctx)

        for task_id in sorted(missing):
            current = ctx.client.get_object(f"/tasks/{task_id}")
            if current is None:
                db.execute(
                    update(MeasurementsVisit)
                    .where(MeasurementsVisit.task_id == task_id)
                    .values(deleted_at=now, deleted_reason="deleted", synced_at=now)
                )
                counters["deleted"] += 1
            else:
                retyped_before = Counter()
                _ingest_task(ctx, current, retyped_before)
                counters["retyped"] += retyped_before["retyped"]
            _commit(ctx)

        for raw in snapshots.values():
            _upsert_lead(ctx, raw)
        if lead_removals:
            db.execute(
                update(MeasurementsLead)
                .where(MeasurementsLead.lead_id.in_(lead_removals))
                .values(deleted_at=now, synced_at=now)
            )
        counters["leads_deleted"] = len(lead_removals)
        _commit(ctx)

    _recompute_all(ctx, counters, now)

    counters["transition_meetings_counted"] = db.scalar(
        select(func.count())
        .select_from(MeasurementsVisit)
        .where(
            MeasurementsVisit.kind == "legacy",
            MeasurementsVisit.deleted_at.is_(None),
            MeasurementsVisit.amo_created_at >= ctx.settings.cutover_at,
        )
    )
    if amo_error is not None:
        raise amo_error


def run_reconcile(ctx: SyncContext) -> None:
    """Raises only AmoAuthError, like the polling streams."""

    def process(_watermark: datetime | None, counters: Counter) -> None:
        _reconcile(ctx, counters)

    _run_stream(ctx, "reconcile", process)
