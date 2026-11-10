"""Outcome and duplicate group of every visit of a lead (ADR-0053 §1, §3).

A pure, deterministic function of a lead's data, like `attribution.attribute`:
no database and no LLM. Events run in `(occurred_at, event_id)` order, days are
New York days, and the result does not depend on the order of the input.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.measurements.zone import ZONE

OUTCOME_RULE_VERSION = 2
"""2: a site_visit group takes the latest effective result of any of its visits."""

WON, LOST = 142, 143
"""amo's closing statuses, the same ids in every pipeline."""


@dataclass(frozen=True)
class Pipelines:
    measurements: int
    qualification: int
    sales: int


@dataclass(frozen=True)
class OutcomeVisit:
    """An active visit: deleted and retyped tasks never reach this function."""

    task_id: int
    scheduled_at: datetime
    responsible_amo_user_id: int
    kind: str
    """Carried for callers; the rule set is chosen by the deadline, never by `kind`."""


@dataclass(frozen=True)
class StatusChange:
    """A `lead_status_changed` event; a missing side of the change is None."""

    event_id: str
    occurred_at: datetime
    before_pipeline: int | None
    before_status: int | None
    after_pipeline: int | None
    after_status: int | None


@dataclass(frozen=True)
class SiteVisitResult:
    """The effective Site Visit Result of one visit.

    `occurred_at` and `event_id` are those of the field event it came from;
    both are None for `snapshot_fallback`, which exists only when the lead has
    no field events at all.
    """

    outcome_type: str
    occurred_at: datetime | None = None
    event_id: str | None = None

    def order(self) -> tuple[bool, datetime | None, str]:
        return (self.occurred_at is not None, self.occurred_at, self.event_id or "")


@dataclass(frozen=True)
class VisitOutcome:
    """One row of `measurements_visit_outcomes`, without the bookkeeping columns.

    `result_source` and the outcome columns are the group's. For `funnel` they
    are those of its first visit (the window is shared). For `site_visit` the
    outcome is the effective result of any visit of the group; with several,
    the one whose field event is latest (ADR-0053, "Уточнения реализации").
    """

    task_id: int
    measurer_key: str | None
    local_date: date
    group_task_id: int
    is_duplicate: bool
    result_source: str
    funnel_outcome: str | None
    no_data_reason: str | None
    funnel_exit_event_id: str | None
    site_visit_outcome: str | None


@dataclass(frozen=True)
class OutcomeResult:
    rows: tuple[VisitOutcome, ...]
    other_exit: int
    """Funnel groups whose first exit went to a pipeline other than M, Q or Sales."""


@dataclass(frozen=True)
class _FunnelOutcome:
    outcome: str
    no_data_reason: str | None = None
    exit_event_id: str | None = None
    other_exit: bool = False


def _day(moment: datetime, zone: ZoneInfo) -> date:
    return moment.astimezone(zone).date()


def _is_exit(change: StatusChange, pipelines: Pipelines) -> bool:
    """Leaves Measurements, or closes inside it. Moves between its stages do not count."""
    if change.before_pipeline != pipelines.measurements:
        return False
    stays_open = change.after_pipeline == pipelines.measurements and change.after_status not in (
        WON,
        LOST,
    )
    return not stays_open


def _is_entry(change: StatusChange, pipelines: Pipelines) -> bool:
    return (
        change.after_pipeline == pipelines.measurements
        and change.before_pipeline != pipelines.measurements
    )


def _is_transparent(
    index: int, changes: list[StatusChange], pipelines: Pipelines, zone: ZoneInfo
) -> bool:
    """An exit to Q/142 that re-enters Measurements later on the same New York day."""
    change = changes[index]
    if (change.after_pipeline, change.after_status) != (pipelines.qualification, WON):
        return False
    exit_day = _day(change.occurred_at, zone)
    return any(
        _is_entry(later, pipelines) and _day(later.occurred_at, zone) == exit_day
        for later in changes[index + 1 :]
    )


def _classify_exit(change: StatusChange, pipelines: Pipelines) -> _FunnelOutcome:
    if change.after_pipeline == pipelines.measurements:
        outcome = "produced" if change.after_status == WON else "closed"
        return _FunnelOutcome(outcome, exit_event_id=change.event_id)
    if change.after_pipeline == pipelines.sales:
        return _FunnelOutcome("produced", exit_event_id=change.event_id)
    if change.after_pipeline == pipelines.qualification:
        return _FunnelOutcome("not_held", exit_event_id=change.event_id)
    return _FunnelOutcome(
        "no_data", no_data_reason="window", exit_event_id=change.event_id, other_exit=True
    )


def _funnel_outcome(
    start: date,
    end: date | None,
    changes: list[StatusChange],
    pipelines: Pipelines,
    ever_in_measurements: bool,
    zone: ZoneInfo,
) -> _FunnelOutcome:
    """The first non-transparent exit whose New York day lies in [start, end)."""
    for index, change in enumerate(changes):
        day = _day(change.occurred_at, zone)
        if day < start or (end is not None and day >= end):
            continue
        if not _is_exit(change, pipelines) or _is_transparent(index, changes, pipelines, zone):
            continue
        return _classify_exit(change, pipelines)
    if not ever_in_measurements:
        return _FunnelOutcome("no_data", no_data_reason="never_in_measurements")
    return _FunnelOutcome("no_data", no_data_reason="window")


def _ever_in_measurements(
    changes: Iterable[StatusChange], pipelines: Pipelines, snapshot_pipeline_id: int | None
) -> bool:
    return snapshot_pipeline_id == pipelines.measurements or any(
        pipelines.measurements in (change.before_pipeline, change.after_pipeline)
        for change in changes
    )


def _group_site_visit_outcome(
    members: list[OutcomeVisit], results: Mapping[int, SiteVisitResult]
) -> str | None:
    found = [results[member.task_id] for member in members if member.task_id in results]
    if not found:
        return None
    return max(found, key=SiteVisitResult.order).outcome_type


def compute_outcomes(
    visits: Iterable[OutcomeVisit],
    status_changes: Iterable[StatusChange],
    cutover_at: datetime,
    measurer_map: Mapping[int, str],
    site_visit_results: Mapping[int, SiteVisitResult],
    pipelines: Pipelines,
    snapshot_pipeline_id: int | None = None,
    zone: ZoneInfo = ZONE,
) -> OutcomeResult:
    """`site_visit_results` maps task_id to its effective Site Visit Result.

    The rule set is chosen by the deadline (`scheduled_at >= cutover_at` is
    `site_visit`), never by `kind`.
    """
    ordered_visits = sorted(visits, key=lambda visit: (visit.scheduled_at, visit.task_id))
    changes = sorted(status_changes, key=lambda change: (change.occurred_at, change.event_id))
    ever_in_measurements = _ever_in_measurements(changes, pipelines, snapshot_pipeline_id)

    groups: dict[tuple[date, str | None], list[OutcomeVisit]] = {}
    for visit in ordered_visits:
        key = (_day(visit.scheduled_at, zone), measurer_map.get(visit.responsible_amo_user_id))
        groups.setdefault(key, []).append(visit)
    days = sorted({day for day, _measurer in groups})

    rows: list[VisitOutcome] = []
    other_exit = 0
    for (day, measurer_key), members in groups.items():
        first = members[0]
        later_days = [other for other in days if other > day]
        if first.scheduled_at >= cutover_at:
            result_source = "site_visit"
            funnel = None
            site_visit_outcome = _group_site_visit_outcome(members, site_visit_results)
        else:
            result_source = "funnel"
            funnel = _funnel_outcome(
                day,
                later_days[0] if later_days else None,
                changes,
                pipelines,
                ever_in_measurements,
                zone,
            )
            other_exit += int(funnel.other_exit)
            site_visit_outcome = None
        for member in members:
            rows.append(
                VisitOutcome(
                    task_id=member.task_id,
                    measurer_key=measurer_key,
                    local_date=day,
                    group_task_id=first.task_id,
                    is_duplicate=member is not first,
                    result_source=result_source,
                    funnel_outcome=funnel.outcome if funnel else None,
                    no_data_reason=funnel.no_data_reason if funnel else None,
                    funnel_exit_event_id=funnel.exit_event_id if funnel else None,
                    site_visit_outcome=site_visit_outcome,
                )
            )
    rows.sort(key=lambda row: row.task_id)
    return OutcomeResult(rows=tuple(rows), other_exit=other_exit)
