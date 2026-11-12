"""Backfill logic (ADR-0051 §4): read everything first, then count or write.

Dry-run and --apply share `collect` and `summarize`, so the counters printed by
a dry-run are the ones an apply would produce. A dry-run writes nothing.
"""

import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from app.measurements.amo_client import AmoClient
from app.measurements.attribution import (
    DeadlineChange,
    FieldChange,
    LeadHistory,
    VisitFacts,
    attribute,
)
from app.measurements.attribution_store import _deadline, _enum_id, recompute_lead
from app.measurements.classification import (
    classify_kind,
    is_post_cutover_meeting_ignored,
    is_transition_meeting,
)
from app.measurements.config import MeasurementsSettings
from app.measurements.models import MeasurementsLead
from app.measurements.sync import (
    _LEAD_STATUS_CHANGED,
    _TASK_DEADLINE_CHANGED,
    _TASK_HISTORY_TYPES,
    INCREMENTAL_STREAMS,
    SyncContext,
    _as_datetime,
    _commit,
    _insert_event,
    _refresh_completed_at,
    _site_visit_enum,
    _state,
    _upsert_lead,
    _upsert_visit,
)
from app.measurements.zone import ZONE

_LEAD_BATCH = 50
_WRITE_BATCH = 100
_COUNTED_RULES = ("unmapped", "no_visit", "ambiguous_decline")
_PROGRESS_EVERY = 100


class Progress:
    """Prints `progress: phase=<name> requests=<n>` to stderr every N requests."""

    def __init__(self, stream=None):
        self.phase = "start"
        self.requests = 0
        self._stream = stream

    def tick(self) -> None:
        self.requests += 1
        if self.requests % _PROGRESS_EVERY == 0:
            print(
                f"progress: phase={self.phase} requests={self.requests}",
                file=self._stream or sys.stderr,
                flush=True,
            )


@dataclass
class Collected:
    tasks: dict[int, dict] = field(default_factory=dict)
    kinds: dict[int, str] = field(default_factory=dict)
    lead_ids: set[int] = field(default_factory=set)
    snapshots: dict[int, dict] = field(default_factory=dict)
    events: dict[str, tuple[dict, int]] = field(default_factory=dict)
    counters: Counter = field(default_factory=Counter)


def _consider_task(collected: Collected, raw: dict, settings: MeasurementsSettings) -> None:
    lead_id = raw.get("entity_id")
    if raw.get("entity_type") != "leads" or lead_id is None:
        collected.counters["tasks.discarded_not_lead"] += 1
        return
    if lead_id in settings.excluded_lead_ids:
        collected.counters["tasks.excluded"] += 1
        return
    facts = (
        raw["task_type_id"],
        raw["responsible_user_id"],
        _as_datetime(raw["complete_till"]),
        _as_datetime(raw["created_at"]),
    )
    kind = classify_kind(settings, *facts)
    if kind is None:
        if is_post_cutover_meeting_ignored(settings, *facts):
            collected.counters["post_cutover_meeting_ignored"] += 1
        return
    collected.tasks[raw["id"]] = raw
    collected.kinds[raw["id"]] = kind
    collected.lead_ids.add(lead_id)


def collect(
    client: AmoClient, settings: MeasurementsSettings, progress: Progress | None = None
) -> Collected:
    """All available legacy history, and new types from cutover_at."""
    progress = progress or Progress()

    def phase(name: str) -> None:
        progress.phase = name

    collected = Collected()
    collected.counters["post_cutover_meeting_ignored"] += 0
    cutover = int(settings.cutover_at.timestamp())

    sources = [
        [("filter[task_type][]", settings.task_type_legacy)],
        [
            ("filter[task_type][]", settings.task_type_primary),
            ("filter[task_type][]", settings.task_type_additional),
            ("filter[updated_at][from]", cutover),
        ],
    ]
    phase("tasks")
    for params in sources:
        for batch in client.iter_pages("/tasks", "tasks", params):
            for raw in batch:
                _consider_task(collected, raw, settings)

    phase("field_events")
    field_params = [
        ("filter[type]", settings.field_event_type),
        ("filter[created_at][from]", cutover),
    ]
    for batch in client.iter_pages("/events", "events", field_params):
        for raw in batch:
            if raw["entity_type"] == "lead" and raw["entity_id"] not in settings.excluded_lead_ids:
                collected.lead_ids.add(raw["entity_id"])

    phase("lead_history")
    lead_types = {settings.field_event_type, _LEAD_STATUS_CHANGED}
    for lead_id in sorted(collected.lead_ids):
        params = [("filter[entity]", "lead"), ("filter[entity_id][]", lead_id)]
        for batch in client.iter_pages("/events", "events", params):
            for raw in batch:
                if raw["type"] in lead_types:
                    collected.events[raw["id"]] = (raw, lead_id)

    phase("task_history")
    for task_id in sorted(collected.tasks):
        lead_id = collected.tasks[task_id]["entity_id"]
        params = [("filter[entity]", "task"), ("filter[entity_id][]", task_id)]
        for batch in client.iter_pages("/events", "events", params):
            for raw in batch:
                if raw["type"] in _TASK_HISTORY_TYPES:
                    collected.events[raw["id"]] = (raw, lead_id)

    phase("leads")
    lead_ids = sorted(collected.lead_ids)
    for start in range(0, len(lead_ids), _LEAD_BATCH):
        params = [("filter[id][]", lead_id) for lead_id in lead_ids[start : start + _LEAD_BATCH]]
        for batch in client.iter_pages("/leads", "leads", params):
            for raw in batch:
                collected.snapshots[raw["id"]] = raw
    return collected


def _history(collected: Collected, lead_id: int, settings: MeasurementsSettings) -> LeadHistory:
    task_ids = {task_id for task_id, raw in collected.tasks.items() if raw["entity_id"] == lead_id}
    visits = tuple(
        VisitFacts(
            task_id=task_id, scheduled_at=_as_datetime(collected.tasks[task_id]["complete_till"])
        )
        for task_id in task_ids
    )
    field_changes, deadline_changes = [], []
    for raw, event_lead in collected.events.values():
        if raw["type"] == settings.field_event_type and event_lead == lead_id:
            field_changes.append(
                FieldChange(
                    event_id=raw["id"],
                    occurred_at=_as_datetime(raw["created_at"]),
                    before=_enum_id(raw.get("value_before")),
                    after=_enum_id(raw.get("value_after")),
                )
            )
        elif raw["type"] == _TASK_DEADLINE_CHANGED and raw["entity_id"] in task_ids:
            deadline_changes.append(
                DeadlineChange(
                    event_id=raw["id"],
                    task_id=raw["entity_id"],
                    occurred_at=_as_datetime(raw["created_at"]),
                    before=_deadline(raw.get("value_before")),
                    after=_deadline(raw.get("value_after")),
                )
            )
    snapshot = collected.snapshots.get(lead_id)
    return LeadHistory(
        visits=visits,
        field_changes=tuple(field_changes),
        deadline_changes=tuple(deadline_changes),
        snapshot_enum_id=_site_visit_enum(snapshot, settings.field_id) if snapshot else None,
        snapshot_known=snapshot is not None,
    )


def summarize(
    collected: Collected, mapping: dict[int, bool | None], settings: MeasurementsSettings
) -> dict[str, int]:
    counters = Counter(collected.counters)
    for task_id, kind in collected.kinds.items():
        raw = collected.tasks[task_id]
        counters[f"tasks.kind.{kind}"] += 1
        measurer = settings.measurer_map.get(raw["responsible_user_id"], "other")
        counters[f"tasks.measurer.{measurer}"] += 1
        if is_transition_meeting(settings, kind, _as_datetime(raw["created_at"])):
            counters["transition_meetings_counted"] += 1
    counters["transition_meetings_counted"] += 0
    counters["leads"] = len(collected.lead_ids)
    counters["leads.without_snapshot"] = len(collected.lead_ids - set(collected.snapshots))
    for raw, _lead_id in collected.events.values():
        counters[f"events.{raw['type']}"] += 1

    for rule in (*_COUNTED_RULES, "drift"):
        counters[rule] += 0
    for lead_id in collected.lead_ids:
        result = attribute(
            _history(collected, lead_id, settings), mapping, settings.cutover_at, ZONE
        )
        counters["drift"] += int(result.drift)
        for row in result.attributions:
            if row.rule in _COUNTED_RULES:
                counters[row.rule] += 1
    return dict(counters)


def apply(
    collected: Collected, ctx: SyncContext, started: datetime, counters: dict[str, int]
) -> None:
    """Writes the collected data with the sync upserts, then recomputes attribution."""
    db = ctx.db
    for lead_id in sorted(collected.lead_ids):
        db.execute(
            insert(MeasurementsLead)
            .values(lead_id=lead_id, synced_at=ctx.now())
            .on_conflict_do_nothing(index_elements=[MeasurementsLead.lead_id])
        )
    for raw in collected.snapshots.values():
        _upsert_lead(ctx, raw)
    _commit(ctx)

    for number, (task_id, raw) in enumerate(sorted(collected.tasks.items()), start=1):
        _upsert_visit(ctx, raw, collected.kinds[task_id])
        if number % _WRITE_BATCH == 0:
            _commit(ctx)
    _commit(ctx)

    for number, (raw, lead_id) in enumerate(collected.events.values(), start=1):
        _insert_event(ctx, raw, lead_id)
        if number % _WRITE_BATCH == 0:
            _commit(ctx)
    for task_id in collected.tasks:
        _refresh_completed_at(ctx, task_id)
    _commit(ctx)

    for lead_id in sorted(collected.lead_ids):
        recompute_lead(db, lead_id, ctx.settings, ctx.now())
        _commit(ctx)

    # Polling continues from the moment the backfill started reading.
    for stream in INCREMENTAL_STREAMS:
        _state(ctx, stream).watermark_at = started
    record = _state(ctx, "backfill")
    record.last_attempt_at = started
    record.last_success_at = ctx.now()
    record.last_status = "ok"
    record.counters = dict(counters)
    _commit(ctx)
