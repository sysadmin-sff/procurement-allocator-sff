"""Decides which visit a Site Visit Result belongs to (ADR-0051 §3).

A pure, deterministic function of a lead's history: no database and no LLM.
Events run in `(occurred_at, event_id)` order and days are counted in the
configured timezone.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

RULE_VERSION = 1


@dataclass(frozen=True)
class VisitFacts:
    task_id: int
    scheduled_at: datetime


@dataclass(frozen=True)
class DeadlineChange:
    event_id: str
    task_id: int
    occurred_at: datetime
    before: datetime | None
    after: datetime | None


@dataclass(frozen=True)
class FieldChange:
    event_id: str
    occurred_at: datetime
    before: int | None
    after: int | None


@dataclass(frozen=True)
class LeadHistory:
    visits: tuple[VisitFacts, ...]
    field_changes: tuple[FieldChange, ...]
    deadline_changes: tuple[DeadlineChange, ...]
    snapshot_enum_id: int | None
    snapshot_known: bool


@dataclass(frozen=True)
class Attribution:
    event_id: str | None
    task_id: int | None
    rule: str
    deadline_source: str | None
    is_effective: bool


@dataclass(frozen=True)
class AttributionResult:
    attributions: tuple[Attribution, ...]
    drift: bool


@dataclass(frozen=True)
class _Held:
    """The result currently standing on a visit."""

    index: int
    enum_id: int
    occurred: bool


class _Deadlines:
    """Answers what a visit's deadline was at a given moment."""

    def __init__(self, changes: tuple[DeadlineChange, ...]):
        self._by_task: dict[int, list[DeadlineChange]] = {}
        for change in sorted(changes, key=lambda item: (item.occurred_at, item.event_id)):
            if change.before is not None and change.after is not None:
                self._by_task.setdefault(change.task_id, []).append(change)

    def at(self, visit: VisitFacts, moment: datetime) -> tuple[datetime, str]:
        changes = self._by_task.get(visit.task_id)
        if not changes:
            return visit.scheduled_at, "current"
        earlier = [change for change in changes if change.occurred_at <= moment]
        if earlier:
            return earlier[-1].after, "history"
        return changes[0].before, "history"


def _pick_occurred(
    deadlines: dict[int, datetime], moment: datetime, zone: ZoneInfo
) -> tuple[int, str]:
    """`same_or_past`, or `early_entry` when every visit is on a later day."""

    def day(value: datetime) -> date:
        return value.astimezone(zone).date()

    def key(task_id: int) -> tuple[datetime, int]:
        return deadlines[task_id], task_id

    event_day = day(moment)
    past = [task_id for task_id, deadline in deadlines.items() if day(deadline) <= event_day]
    if not past:
        return min(deadlines, key=key), "early_entry"

    same_day = [task_id for task_id in past if day(deadlines[task_id]) == event_day]
    if not same_day:
        return max(past, key=key), "same_or_past"
    already_due = [task_id for task_id in same_day if deadlines[task_id] <= moment]
    if already_due:
        return max(already_due, key=key), "same_or_past"
    return min(same_day, key=key), "same_or_past"


def _pick_declined(
    deadlines: dict[int, datetime], moment: datetime, held: dict[int, _Held]
) -> tuple[int, str]:
    """`upcoming`, or `late_decline` when no free visit lies ahead."""

    def key(task_id: int) -> tuple[datetime, int]:
        return deadlines[task_id], task_id

    free_ahead = [
        task_id
        for task_id, deadline in deadlines.items()
        if deadline >= moment and not (task_id in held and held[task_id].occurred)
    ]
    if free_ahead:
        return min(free_ahead, key=key), "upcoming"
    past = [task_id for task_id, deadline in deadlines.items() if deadline < moment]
    return max(past or deadlines, key=key), "late_decline"


def attribute(
    history: LeadHistory,
    visit_occurred: Mapping[int, bool | None],
    cutover_at: datetime,
    zone: ZoneInfo,
) -> AttributionResult:
    """Applies the rule table. A missing or NULL mapping means `unmapped`."""
    visits = [visit for visit in history.visits if visit.scheduled_at >= cutover_at]
    changes = sorted(history.field_changes, key=lambda item: (item.occurred_at, item.event_id))
    deadlines = _Deadlines(history.deadline_changes)

    rows: list[Attribution] = []
    held: dict[int, _Held] = {}

    for change in changes:
        if change.after is None:
            if change.before is None:
                continue
            # The last attachment of this value is the visit that was holding it.
            target = max(
                (task_id for task_id, item in held.items() if item.enum_id == change.before),
                key=lambda task_id: held[task_id].index,
                default=None,
            )
            rows.append(Attribution(change.event_id, target, "cleared", None, False))
            if target is not None:
                del held[target]
            continue

        occurred = visit_occurred.get(change.after)
        if occurred is None:
            rows.append(Attribution(change.event_id, None, "unmapped", None, False))
            continue
        if not visits:
            rows.append(Attribution(change.event_id, None, "no_visit", None, False))
            continue

        resolved = {visit.task_id: deadlines.at(visit, change.occurred_at) for visit in visits}
        moments = {task_id: item[0] for task_id, item in resolved.items()}
        if occurred:
            task_id, rule = _pick_occurred(moments, change.occurred_at, zone)
        else:
            task_id, rule = _pick_declined(moments, change.occurred_at, held)
        rows.append(Attribution(change.event_id, task_id, rule, resolved[task_id][1], False))
        held[task_id] = _Held(index=len(rows) - 1, enum_id=change.after, occurred=occurred)

    if not changes and history.snapshot_known and history.snapshot_enum_id is not None:
        if visit_occurred.get(history.snapshot_enum_id) is None:
            rows.append(Attribution(None, None, "unmapped", None, False))
        elif not visits:
            rows.append(Attribution(None, None, "no_visit", None, False))
        else:
            last = max(visits, key=lambda visit: (visit.scheduled_at, visit.task_id))
            rows.append(Attribution(None, last.task_id, "snapshot_fallback", "current", True))

    for item in held.values():
        rows[item.index] = replace(rows[item.index], is_effective=True)

    drift = (
        bool(changes) and history.snapshot_known and (changes[-1].after != history.snapshot_enum_id)
    )
    return AttributionResult(attributions=tuple(rows), drift=drift)
