"""Reads amo into the measurements tables (ADR-0051 §3, §4).

Every page is committed on its own, which keeps transactions short and is safe
because all writes are idempotent. A stream's watermark moves only after its
whole window has succeeded, so a failed window is simply read again.
"""

import logging
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, or_, select, tuple_, union, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.measurements.amo_client import AmoAuthError, AmoClient, AmoError, AmoHttpError
from app.measurements.attribution_store import recompute_lead
from app.measurements.classification import (
    classify_kind,
    is_post_cutover_meeting_ignored,
    is_transition_meeting,
)
from app.measurements.config import MeasurementsSettings
from app.measurements.models import (
    MeasurementsAmoEvent,
    MeasurementsAmoUser,
    MeasurementsFieldValue,
    MeasurementsLead,
    MeasurementsPipelineStatus,
    MeasurementsSyncState,
    MeasurementsVisit,
)
from app.measurements.zone import ZONE

logger = logging.getLogger(__name__)

_OVERLAP = timedelta(minutes=2)
_LEAD_BATCH = 50
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_LEAD_STATUS_CHANGED = "lead_status_changed"
_TASK_DEADLINE_CHANGED = "task_deadline_changed"
_TASK_DELETED = "task_deleted"
_TASK_COMPLETED = "task_completed"
_TASK_TYPE_CHANGED = "task_type_changed"
_TASK_HISTORY_TYPES = {
    _TASK_DEADLINE_CHANGED,
    _TASK_DELETED,
    _TASK_COMPLETED,
    _TASK_TYPE_CHANGED,
}


# Names of the polling streams run by run_cycle, in order; the backfill sets
# their watermarks.
INCREMENTAL_STREAMS = (
    "tasks_new",
    "tasks_legacy",
    "events_field",
    "events_lead_status",
    "events_task_deadline",
    "events_task_deleted",
    "events_task_completed",
    "events_task_type",
    "leads",
    "attribution",
)


@dataclass
class SyncContext:
    db: Session
    client: AmoClient
    settings: MeasurementsSettings
    now: Callable[[], datetime]
    heartbeat: Callable[[], None] | None = None
    """Called before each commit, so long runs keep the worker heartbeat fresh."""


class ReconcileAborted(Exception):
    """The nightly reconciliation would remove too many rows and wrote nothing."""


def _commit(ctx: SyncContext) -> None:
    if ctx.heartbeat is not None:
        ctx.heartbeat()
    ctx.db.commit()


def _as_datetime(timestamp: int | None) -> datetime | None:
    return None if timestamp is None else datetime.fromtimestamp(timestamp, timezone.utc)


# --- events


def _insert_event(ctx: SyncContext, raw: dict, lead_id: int | None) -> bool:
    """Returns True if the event was new. Events are append-only."""
    statement = (
        insert(MeasurementsAmoEvent)
        .values(
            event_id=raw["id"],
            event_type=raw["type"],
            entity_type=raw["entity_type"],
            entity_id=raw["entity_id"],
            lead_id=lead_id,
            occurred_at=_as_datetime(raw["created_at"]),
            amo_user_id=raw.get("created_by"),
            value_before=raw.get("value_before"),
            value_after=raw.get("value_after"),
            ingested_at=ctx.now(),
        )
        .on_conflict_do_nothing(index_elements=[MeasurementsAmoEvent.event_id])
        .returning(MeasurementsAmoEvent.event_id)
    )
    return ctx.db.execute(statement).first() is not None


def _load_lead_history(ctx: SyncContext, lead_id: int) -> None:
    wanted = {ctx.settings.field_event_type, _LEAD_STATUS_CHANGED}
    params = [("filter[entity]", "lead"), ("filter[entity_id][]", lead_id)]
    for batch in ctx.client.iter_pages("/events", "events", params):
        for raw in batch:
            if raw["type"] in wanted:
                _insert_event(ctx, raw, lead_id)


def _load_task_history(ctx: SyncContext, task_id: int, lead_id: int) -> None:
    params = [("filter[entity]", "task"), ("filter[entity_id][]", task_id)]
    for batch in ctx.client.iter_pages("/events", "events", params):
        for raw in batch:
            if raw["type"] in _TASK_HISTORY_TYPES:
                _insert_event(ctx, raw, lead_id)


# --- leads


def _lead_is_known(ctx: SyncContext, lead_id: int) -> bool:
    statement = select(MeasurementsLead.lead_id).where(MeasurementsLead.lead_id == lead_id)
    return ctx.db.execute(statement).first() is not None


def _ensure_lead(ctx: SyncContext, lead_id: int) -> None:
    """Registers a lead, loading its history the first time it is seen."""
    statement = (
        insert(MeasurementsLead)
        .values(lead_id=lead_id, synced_at=ctx.now())
        .on_conflict_do_nothing(index_elements=[MeasurementsLead.lead_id])
        .returning(MeasurementsLead.lead_id)
    )
    if ctx.db.execute(statement).first() is not None:
        _load_lead_history(ctx, lead_id)


def _site_visit_enum(raw: dict, field_id: int) -> int | None:
    for field in raw.get("custom_fields_values") or []:
        if field.get("field_id") == field_id:
            values = field.get("values") or []
            return values[0].get("enum_id") if values else None
    return None


def _upsert_lead(ctx: SyncContext, raw: dict) -> None:
    table = MeasurementsLead.__table__
    values = {
        "pipeline_id": raw.get("pipeline_id"),
        "status_id": raw.get("status_id"),
        "site_visit_enum_id": _site_visit_enum(raw, ctx.settings.field_id),
        "closed_at": _as_datetime(raw.get("closed_at")),
        "price": raw.get("price"),
        "amo_updated_at": _as_datetime(raw.get("updated_at")),
        "deleted_at": None,
        "synced_at": ctx.now(),
    }
    statement = insert(table).values(lead_id=raw["id"], **values)
    ctx.db.execute(
        statement.on_conflict_do_update(
            index_elements=[table.c.lead_id],
            set_={name: statement.excluded[name] for name in values},
            where=or_(
                table.c.amo_updated_at.is_(None),
                statement.excluded.amo_updated_at >= table.c.amo_updated_at,
            ),
        )
    )


# --- tasks


def _visit_row(ctx: SyncContext, task_id: int):
    table = MeasurementsVisit.__table__
    statement = select(table.c.lead_id, table.c.amo_updated_at, table.c.is_completed).where(
        table.c.task_id == task_id
    )
    return ctx.db.execute(statement).first()


def _refresh_completed_at(ctx: SyncContext, task_id: int) -> None:
    """`completed_at` follows the task_completed events of a still-completed task."""
    row = _visit_row(ctx, task_id)
    if row is None:
        return
    latest = None
    if row.is_completed:
        latest = ctx.db.scalar(
            select(func.max(MeasurementsAmoEvent.occurred_at)).where(
                MeasurementsAmoEvent.entity_type == "task",
                MeasurementsAmoEvent.entity_id == task_id,
                MeasurementsAmoEvent.event_type == _TASK_COMPLETED,
            )
        )
    ctx.db.execute(
        update(MeasurementsVisit)
        .where(MeasurementsVisit.task_id == task_id)
        .values(completed_at=latest)
    )


def _mark_retyped(ctx: SyncContext, task_id: int, raw: dict) -> None:
    """Keeps the current type and responsible, so `kind` can be re-derived from our data."""
    ctx.db.execute(
        update(MeasurementsVisit)
        .where(MeasurementsVisit.task_id == task_id, MeasurementsVisit.deleted_at.is_(None))
        .values(
            deleted_at=ctx.now(),
            deleted_reason="retyped",
            task_type_id=raw["task_type_id"],
            responsible_amo_user_id=raw["responsible_user_id"],
            amo_updated_at=_as_datetime(raw["updated_at"]),
            synced_at=ctx.now(),
        )
    )


def _is_all_day(ctx: SyncContext, complete_till: datetime, duration: int | None) -> bool:
    local = complete_till.astimezone(ZONE)
    return local.hour == 23 and local.minute == 59 and duration == 0


def _result_text(raw: dict) -> str | None:
    # amo returns an object when there is a result and an empty list when there is not.
    result = raw.get("result")
    return result.get("text") if isinstance(result, dict) else None


def _upsert_visit(ctx: SyncContext, raw: dict, kind: str) -> None:
    table = MeasurementsVisit.__table__
    complete_till = _as_datetime(raw["complete_till"])
    values = {
        "lead_id": raw["entity_id"],
        "task_type_id": raw["task_type_id"],
        "kind": kind,
        "responsible_amo_user_id": raw["responsible_user_id"],
        "scheduled_at": complete_till,
        "duration": raw.get("duration"),
        "is_all_day": _is_all_day(ctx, complete_till, raw.get("duration")),
        "is_completed": raw["is_completed"],
        "result_text": _result_text(raw),
        "amo_created_at": _as_datetime(raw["created_at"]),
        "amo_updated_at": _as_datetime(raw["updated_at"]),
        "synced_at": ctx.now(),
    }
    statement = insert(table).values(task_id=raw["id"], **values)
    excluded = statement.excluded
    # A row read in the same state as when it was deleted is stale, not a restoration.
    stale_deletion = (table.c.deleted_reason == "deleted") & (
        excluded.amo_updated_at == table.c.amo_updated_at
    )
    ctx.db.execute(
        statement.on_conflict_do_update(
            index_elements=[table.c.task_id],
            set_={
                **{name: excluded[name] for name in values},
                "deleted_at": case((stale_deletion, table.c.deleted_at), else_=None),
                "deleted_reason": case((stale_deletion, table.c.deleted_reason), else_=None),
            },
            where=excluded.amo_updated_at >= table.c.amo_updated_at,
        )
    )


def _ingest_task(ctx: SyncContext, raw: dict, counters: Counter) -> None:
    lead_id = raw.get("entity_id")
    if raw.get("entity_type") != "leads" or lead_id is None:
        counters["discarded"] += 1
        return
    if lead_id in ctx.settings.excluded_lead_ids:
        counters["excluded"] += 1
        return

    task_id = raw["id"]
    known = _visit_row(ctx, task_id)
    facts = (
        raw["task_type_id"],
        raw["responsible_user_id"],
        _as_datetime(raw["complete_till"]),
        _as_datetime(raw["created_at"]),
    )
    kind = classify_kind(ctx.settings, *facts)
    if kind is None:
        if is_post_cutover_meeting_ignored(ctx.settings, *facts):
            counters["post_cutover_meeting_ignored"] += 1
        if known is not None and _as_datetime(raw["updated_at"]) >= known.amo_updated_at:
            _mark_retyped(ctx, task_id, raw)
            counters["retyped"] += 1
        return

    _ensure_lead(ctx, lead_id)
    _upsert_visit(ctx, raw, kind)
    if known is None:
        _load_task_history(ctx, task_id, lead_id)
    _refresh_completed_at(ctx, task_id)
    counters["stored"] += 1
    if is_transition_meeting(ctx.settings, kind, _as_datetime(raw["created_at"])):
        counters["transition_meetings_counted"] += 1


# --- streams


def _state(ctx: SyncContext, stream: str) -> MeasurementsSyncState:
    state = ctx.db.get(MeasurementsSyncState, stream)
    if state is None:
        state = MeasurementsSyncState(stream=stream, consecutive_failures=0, counters={})
        ctx.db.add(state)
        ctx.db.flush()
    return state


def _run_stream(
    ctx: SyncContext,
    stream: str,
    process: Callable[[datetime | None, Counter], None],
) -> None:
    """Runs one window. Non-auth failures stay local to the stream."""
    started = ctx.now()
    state = _state(ctx, stream)
    state.last_attempt_at = started
    state.last_status = "running"
    watermark = state.watermark_at
    ctx.db.commit()

    counters: Counter = Counter()
    retries_before = ctx.client.transport_retries
    try:
        process(watermark, counters)
    except Exception as exc:
        counters["transport_retries"] = ctx.client.transport_retries - retries_before
        ctx.db.rollback()
        state = _state(ctx, stream)
        if isinstance(exc, AmoAuthError):
            state.last_status = "auth_failed"
        elif isinstance(exc, ReconcileAborted):
            state.last_status = "aborted"
        else:
            state.last_status = "error"
        state.last_http_status = exc.status_code if isinstance(exc, AmoError) else None
        state.consecutive_failures += 1
        state.counters = dict(counters)
        ctx.db.commit()
        logger.warning("measurements stream %s failed: %s", stream, type(exc).__name__)
        if isinstance(exc, AmoAuthError):
            raise
        return

    counters["transport_retries"] = ctx.client.transport_retries - retries_before
    state = _state(ctx, stream)
    state.watermark_at = started
    state.last_success_at = started
    state.last_status = "ok"
    state.last_http_status = None
    state.consecutive_failures = 0
    state.counters = dict(counters)
    ctx.db.commit()


def _window_start(ctx: SyncContext, watermark: datetime | None) -> int:
    return int(((watermark or ctx.settings.cutover_at) - _OVERLAP).timestamp())


def _tasks_stream(ctx: SyncContext, task_types: Iterable[int]):
    def process(watermark: datetime | None, counters: Counter) -> None:
        params = [("filter[task_type][]", task_type) for task_type in task_types]
        params.append(("filter[updated_at][from]", _window_start(ctx, watermark)))
        for batch in ctx.client.iter_pages("/tasks", "tasks", params):
            for raw in batch:
                _ingest_task(ctx, raw, counters)
            _commit(ctx)

    return process


def _events_stream(ctx: SyncContext, event_type: str, handle: Callable[[dict, Counter], None]):
    def process(watermark: datetime | None, counters: Counter) -> None:
        params = [
            ("filter[type]", event_type),
            ("filter[created_at][from]", _window_start(ctx, watermark)),
        ]
        for batch in ctx.client.iter_pages("/events", "events", params):
            for raw in batch:
                handle(raw, counters)
            _commit(ctx)

    return process


def _handle_field_event(ctx: SyncContext, raw: dict, counters: Counter) -> None:
    lead_id = raw["entity_id"]
    if raw["entity_type"] != "lead" or lead_id in ctx.settings.excluded_lead_ids:
        counters["discarded"] += 1
        return
    _ensure_lead(ctx, lead_id)
    _insert_event(ctx, raw, lead_id)
    counters["stored"] += 1


def _handle_status_event(ctx: SyncContext, raw: dict, counters: Counter) -> None:
    lead_id = raw["entity_id"]
    if raw["entity_type"] != "lead" or not _lead_is_known(ctx, lead_id):
        counters["discarded"] += 1
        return
    _insert_event(ctx, raw, lead_id)
    counters["stored"] += 1


def _handle_task_event(ctx: SyncContext, raw: dict, counters: Counter) -> None:
    """Only known tasks: a task seen later gets these from its history load."""
    task_id = raw["entity_id"]
    row = _visit_row(ctx, task_id) if raw["entity_type"] == "task" else None
    if row is None:
        counters["discarded"] += 1
        return
    _insert_event(ctx, raw, row.lead_id)
    if raw["type"] == _TASK_DELETED:
        ctx.db.execute(
            update(MeasurementsVisit)
            .where(MeasurementsVisit.task_id == task_id)
            .values(
                deleted_at=_as_datetime(raw["created_at"]),
                deleted_reason="deleted",
                synced_at=ctx.now(),
            )
        )
    elif raw["type"] == _TASK_COMPLETED:
        _refresh_completed_at(ctx, task_id)
    counters["stored"] += 1


def _visit_task_types(settings: MeasurementsSettings) -> set[int]:
    return {settings.task_type_primary, settings.task_type_additional, settings.task_type_legacy}


def _handle_type_changed(ctx: SyncContext, raw: dict, counters: Counter) -> None:
    """amo's event says only that the type changed, so the task is read again."""
    task_id = raw["entity_id"]
    known = _visit_row(ctx, task_id) if raw["entity_type"] == "task" else None
    after = raw.get("value_after") or []
    new_type = after[0].get("task_type", {}).get("id") if after else None

    if known is None:
        if new_type not in _visit_task_types(ctx.settings):
            counters["discarded"] += 1
            return
    elif not _insert_event(ctx, raw, known.lead_id):
        return

    current = ctx.client.get_object(f"/tasks/{task_id}")
    if current is None:
        counters["missing"] += 1
        return
    _ingest_task(ctx, current, counters)
    row = _visit_row(ctx, task_id)
    if row is not None:
        _insert_event(ctx, raw, row.lead_id)


def _changed_lead_ids(
    ctx: SyncContext, watermark: datetime | None, *, include_snapshots: bool = False
) -> list[int]:
    """Leads without a snapshot, or touched since the last successful read."""
    since = watermark or _EPOCH
    sources = [
        select(MeasurementsLead.lead_id).where(MeasurementsLead.amo_updated_at.is_(None)),
        select(MeasurementsVisit.lead_id).where(MeasurementsVisit.synced_at > since),
        select(MeasurementsAmoEvent.lead_id).where(
            MeasurementsAmoEvent.lead_id.is_not(None), MeasurementsAmoEvent.ingested_at > since
        ),
    ]
    if include_snapshots:
        sources.append(select(MeasurementsLead.lead_id).where(MeasurementsLead.synced_at > since))
    return sorted(ctx.db.scalars(union(*sources)).all())


def _leads_stream(ctx: SyncContext):
    def process(watermark: datetime | None, counters: Counter) -> None:
        wanted = [
            lead_id
            for lead_id in _changed_lead_ids(ctx, watermark)
            if lead_id not in ctx.settings.excluded_lead_ids
        ]
        for start in range(0, len(wanted), _LEAD_BATCH):
            params = [("filter[id][]", lead_id) for lead_id in wanted[start : start + _LEAD_BATCH]]
            for batch in ctx.client.iter_pages("/leads", "leads", params):
                for raw in batch:
                    _upsert_lead(ctx, raw)
                    counters["stored"] += 1
                _commit(ctx)

    return process


def _attribution_stream(ctx: SyncContext):
    def process(watermark: datetime | None, counters: Counter) -> None:
        for lead_id in _changed_lead_ids(ctx, watermark, include_snapshots=True):
            result = recompute_lead(ctx.db, lead_id, ctx.settings, ctx.now())
            _commit(ctx)
            counters["recomputed"] += 1
            counters["drift"] += int(result.drift)
            for row in result.attributions:
                if row.rule in ("unmapped", "no_visit", "ambiguous_decline"):
                    counters[row.rule] += 1

    return process


def run_cycle(ctx: SyncContext) -> None:
    """One polling pass. Tasks go first so that their events find them known."""
    settings = ctx.settings

    def handler(function):
        return lambda raw, counters: function(ctx, raw, counters)

    streams = [
        (
            "tasks_new",
            _tasks_stream(ctx, [settings.task_type_primary, settings.task_type_additional]),
        ),
        ("tasks_legacy", _tasks_stream(ctx, [settings.task_type_legacy])),
        (
            "events_field",
            _events_stream(ctx, settings.field_event_type, handler(_handle_field_event)),
        ),
        (
            "events_lead_status",
            _events_stream(ctx, _LEAD_STATUS_CHANGED, handler(_handle_status_event)),
        ),
        (
            "events_task_deadline",
            _events_stream(ctx, _TASK_DEADLINE_CHANGED, handler(_handle_task_event)),
        ),
        ("events_task_deleted", _events_stream(ctx, _TASK_DELETED, handler(_handle_task_event))),
        (
            "events_task_completed",
            _events_stream(ctx, _TASK_COMPLETED, handler(_handle_task_event)),
        ),
        (
            "events_task_type",
            _events_stream(ctx, _TASK_TYPE_CHANGED, handler(_handle_type_changed)),
        ),
        ("leads", _leads_stream(ctx)),
        ("attribution", _attribution_stream(ctx)),
    ]
    assert tuple(name for name, _ in streams) == INCREMENTAL_STREAMS
    for stream, process in streams:
        _run_stream(ctx, stream, process)


# --- reference data


def _custom_fields_stream(ctx: SyncContext):
    def process(_watermark: datetime | None, counters: Counter) -> None:
        field = next(
            (
                raw
                for batch in ctx.client.iter_pages("/leads/custom_fields", "custom_fields")
                for raw in batch
                if raw["id"] == ctx.settings.field_id
            ),
            None,
        )
        if field is None:
            raise AmoHttpError("site visit field not found in amo")

        table = MeasurementsFieldValue.__table__
        seen = []
        for enum in field.get("enums") or []:
            seen.append(enum["id"])
            statement = insert(table).values(
                enum_id=enum["id"], label=enum["value"], sort=enum.get("sort"), is_active=True
            )
            # The outcome mapping is deliberately absent: sync never overwrites it.
            ctx.db.execute(
                statement.on_conflict_do_update(
                    index_elements=[table.c.enum_id],
                    set_={
                        "label": statement.excluded.label,
                        "sort": statement.excluded.sort,
                        "is_active": True,
                    },
                )
            )
            counters["stored"] += 1
        ctx.db.execute(update(table).where(table.c.enum_id.not_in(seen)).values(is_active=False))
        _commit(ctx)

    return process


def _users_stream(ctx: SyncContext):
    def process(_watermark: datetime | None, counters: Counter) -> None:
        table = MeasurementsAmoUser.__table__
        seen: list[int] = []
        for batch in ctx.client.iter_pages("/users", "users"):
            for raw in batch:
                seen.append(raw["id"])
                values = {
                    "name": raw["name"],
                    "is_active": bool((raw.get("rights") or {}).get("is_active", True)),
                    "synced_at": ctx.now(),
                    "missing_since": None,
                }
                statement = insert(table).values(amo_user_id=raw["id"], **values)
                ctx.db.execute(
                    statement.on_conflict_do_update(
                        index_elements=[table.c.amo_user_id],
                        set_={name: statement.excluded[name] for name in values},
                    )
                )
                counters["stored"] += 1
            _commit(ctx)
        counters["missing"] = _mark_missing(ctx, table, table.c.amo_user_id.not_in(seen), seen)

    return process


def _mark_missing(ctx: SyncContext, table, absent, seen: list) -> int:
    """Marks rows amo no longer returns; never deletes. An empty answer marks nothing."""
    if not seen:
        return 0
    result = ctx.db.execute(
        update(table).where(absent, table.c.missing_since.is_(None)).values(missing_since=ctx.now())
    )
    _commit(ctx)
    return result.rowcount


def _pipelines_stream(ctx: SyncContext):
    def process(_watermark: datetime | None, counters: Counter) -> None:
        table = MeasurementsPipelineStatus.__table__
        seen: list[tuple[int, int]] = []
        for batch in ctx.client.iter_pages("/leads/pipelines", "pipelines"):
            for pipeline in batch:
                for status in (pipeline.get("_embedded") or {}).get("statuses", []):
                    seen.append((pipeline["id"], status["id"]))
                    values = {
                        "pipeline_name": pipeline["name"],
                        "status_name": status["name"],
                        "sort": status.get("sort"),
                        "is_archived": bool(pipeline.get("is_archive", False)),
                        "synced_at": ctx.now(),
                        "missing_since": None,
                    }
                    statement = insert(table).values(
                        pipeline_id=pipeline["id"], status_id=status["id"], **values
                    )
                    ctx.db.execute(
                        statement.on_conflict_do_update(
                            index_elements=[table.c.pipeline_id, table.c.status_id],
                            set_={name: statement.excluded[name] for name in values},
                        )
                    )
                    counters["stored"] += 1
            _commit(ctx)
        absent = tuple_(table.c.pipeline_id, table.c.status_id).not_in(seen)
        counters["missing"] = _mark_missing(ctx, table, absent, seen)

    return process


def run_reference_cycle(ctx: SyncContext) -> None:
    """Hourly reference data (ADR-0051 §4)."""
    _run_stream(ctx, "reference_custom_fields", _custom_fields_stream(ctx))
    _run_stream(ctx, "reference_users", _users_stream(ctx))
    _run_stream(ctx, "reference_pipelines", _pipelines_stream(ctx))
