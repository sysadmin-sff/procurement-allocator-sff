"""Loads a lead's data and replaces its derived rows (ADR-0051 §3, ADR-0053 §3).

Attributions and visit outcomes of a lead are replaced together, in the
caller's transaction. An excluded or deleted lead keeps no derived rows.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.measurements.attribution import (
    RULE_VERSION,
    AttributionResult,
    DeadlineChange,
    FieldChange,
    LeadHistory,
    VisitFacts,
    attribute,
)
from app.measurements.config import MeasurementsSettings
from app.measurements.models import (
    MeasurementsAmoEvent,
    MeasurementsFieldValue,
    MeasurementsLead,
    MeasurementsResultAttribution,
    MeasurementsVisit,
    MeasurementsVisitOutcome,
)
from app.measurements.outcomes import (
    OUTCOME_RULE_VERSION,
    OutcomeResult,
    OutcomeVisit,
    Pipelines,
    SiteVisitResult,
    StatusChange,
    compute_outcomes,
)
from app.measurements.zone import ZONE

_TASK_DEADLINE_CHANGED = "task_deadline_changed"
_LEAD_STATUS_CHANGED = "lead_status_changed"


def _enum_id(value: list | None) -> int | None:
    """amo's empty value is `[]`."""
    return value[0]["custom_field_value"].get("enum_id") if value else None


def _deadline(value: list | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(value[0]["task_deadline"]["timestamp"], timezone.utc)


def _load_history(db: Session, lead_id: int, settings: MeasurementsSettings) -> LeadHistory:
    visits = tuple(
        VisitFacts(task_id=row.task_id, scheduled_at=row.scheduled_at)
        for row in db.execute(
            select(MeasurementsVisit.task_id, MeasurementsVisit.scheduled_at).where(
                MeasurementsVisit.lead_id == lead_id, MeasurementsVisit.deleted_at.is_(None)
            )
        )
    )

    field_changes = tuple(
        FieldChange(
            event_id=event.event_id,
            occurred_at=event.occurred_at,
            before=_enum_id(event.value_before),
            after=_enum_id(event.value_after),
        )
        for event in db.execute(
            select(MeasurementsAmoEvent).where(
                MeasurementsAmoEvent.lead_id == lead_id,
                MeasurementsAmoEvent.event_type == settings.field_event_type,
            )
        ).scalars()
    )

    deadline_changes: tuple[DeadlineChange, ...] = ()
    if visits:
        deadline_changes = tuple(
            DeadlineChange(
                event_id=event.event_id,
                task_id=event.entity_id,
                occurred_at=event.occurred_at,
                before=_deadline(event.value_before),
                after=_deadline(event.value_after),
            )
            for event in db.execute(
                select(MeasurementsAmoEvent).where(
                    MeasurementsAmoEvent.entity_type == "task",
                    MeasurementsAmoEvent.event_type == _TASK_DEADLINE_CHANGED,
                    MeasurementsAmoEvent.entity_id.in_([visit.task_id for visit in visits]),
                )
            ).scalars()
        )

    lead = db.execute(
        select(MeasurementsLead.site_visit_enum_id, MeasurementsLead.amo_updated_at).where(
            MeasurementsLead.lead_id == lead_id
        )
    ).first()

    return LeadHistory(
        visits=visits,
        field_changes=field_changes,
        deadline_changes=deadline_changes,
        snapshot_enum_id=lead.site_visit_enum_id if lead else None,
        snapshot_known=lead is not None and lead.amo_updated_at is not None,
    )


@dataclass(frozen=True)
class LeadDerived:
    """Everything recomputed for one lead, before it is written."""

    attribution: AttributionResult
    outcomes: OutcomeResult
    kinds: dict[int, str]
    """task_id -> kind of the lead's active visits, for counters."""
    skipped: bool
    """Excluded or deleted lead: its rows are removed and none are written."""


_SKIPPED = LeadDerived(
    attribution=AttributionResult(attributions=(), drift=False),
    outcomes=OutcomeResult(rows=(), other_exit=0),
    kinds={},
    skipped=True,
)


def _status_side(value: list | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    status = value[0].get("lead_status") or {}
    return status.get("pipeline_id"), status.get("id")


def _effective_results(
    history: LeadHistory, result: AttributionResult, outcome_types: dict[int, str | None]
) -> dict[int, SiteVisitResult]:
    """task_id -> the result standing on that visit, with its field event."""
    changes = {change.event_id: change for change in history.field_changes}
    found: dict[int, SiteVisitResult] = {}
    for row in result.attributions:
        if not row.is_effective or row.task_id is None:
            continue
        change = changes.get(row.event_id) if row.event_id is not None else None
        enum_id = history.snapshot_enum_id if row.event_id is None else change.after
        outcome_type = outcome_types.get(enum_id)
        if outcome_type is not None:
            found[row.task_id] = SiteVisitResult(
                outcome_type,
                occurred_at=change.occurred_at if change else None,
                event_id=row.event_id,
            )
    return found


def _status_changes(db: Session, lead_id: int) -> list[StatusChange]:
    changes = []
    for event in db.execute(
        select(MeasurementsAmoEvent).where(
            MeasurementsAmoEvent.lead_id == lead_id,
            MeasurementsAmoEvent.event_type == _LEAD_STATUS_CHANGED,
        )
    ).scalars():
        before = _status_side(event.value_before)
        after = _status_side(event.value_after)
        changes.append(StatusChange(event.event_id, event.occurred_at, *before, *after))
    return changes


def load_field_values(db: Session) -> list:
    """The Site Visit Result mapping: (enum_id, visit_occurred, outcome_type) rows."""
    return db.execute(
        select(
            MeasurementsFieldValue.enum_id,
            MeasurementsFieldValue.visit_occurred,
            MeasurementsFieldValue.outcome_type,
        )
    ).all()


def compute_lead(
    db: Session, lead_id: int, settings: MeasurementsSettings, field_values: list | None = None
) -> LeadDerived:
    """Reads only: the dry-run of the recompute script calls this alone.

    A caller recomputing many leads passes `field_values` read once.
    """
    lead = db.execute(
        select(MeasurementsLead.pipeline_id, MeasurementsLead.deleted_at).where(
            MeasurementsLead.lead_id == lead_id
        )
    ).first()
    if lead_id in settings.excluded_lead_ids or (lead is not None and lead.deleted_at is not None):
        return _SKIPPED

    if field_values is None:
        field_values = load_field_values(db)
    history = _load_history(db, lead_id, settings)
    attribution = attribute(
        history,
        {row.enum_id: row.visit_occurred for row in field_values},
        settings.cutover_at,
        ZONE,
    )

    visits = db.execute(
        select(
            MeasurementsVisit.task_id,
            MeasurementsVisit.scheduled_at,
            MeasurementsVisit.responsible_amo_user_id,
            MeasurementsVisit.kind,
        ).where(MeasurementsVisit.lead_id == lead_id, MeasurementsVisit.deleted_at.is_(None))
    ).all()
    outcomes = compute_outcomes(
        [
            OutcomeVisit(row.task_id, row.scheduled_at, row.responsible_amo_user_id, row.kind)
            for row in visits
        ],
        _status_changes(db, lead_id),
        settings.cutover_at,
        settings.measurer_map,
        _effective_results(
            history, attribution, {row.enum_id: row.outcome_type for row in field_values}
        ),
        Pipelines(
            measurements=settings.pipeline_measurements_id,
            qualification=settings.pipeline_qualification_id,
            sales=settings.pipeline_sales_id,
        ),
        snapshot_pipeline_id=lead.pipeline_id if lead is not None else None,
        zone=ZONE,
    )
    return LeadDerived(
        attribution=attribution,
        outcomes=outcomes,
        kinds={row.task_id: row.kind for row in visits},
        skipped=False,
    )


def write_lead(db: Session, lead_id: int, derived: LeadDerived, computed_at: datetime) -> None:
    """Replaces the lead's attributions and outcomes. Does not commit."""
    attributions = MeasurementsResultAttribution.__table__
    outcomes = MeasurementsVisitOutcome.__table__
    db.execute(delete(attributions).where(attributions.c.lead_id == lead_id))
    db.execute(delete(outcomes).where(outcomes.c.lead_id == lead_id))
    if derived.attribution.attributions:
        db.execute(
            insert(attributions),
            [
                {
                    "id": uuid.uuid4(),
                    "event_id": row.event_id,
                    "lead_id": lead_id,
                    "task_id": row.task_id,
                    "rule": row.rule,
                    "deadline_source": row.deadline_source,
                    "is_effective": row.is_effective,
                    "rule_version": RULE_VERSION,
                    "computed_at": computed_at,
                }
                for row in derived.attribution.attributions
            ],
        )
    if derived.outcomes.rows:
        db.execute(
            insert(outcomes),
            [
                {
                    "task_id": row.task_id,
                    "lead_id": lead_id,
                    "measurer_key": row.measurer_key,
                    "local_date": row.local_date,
                    "group_task_id": row.group_task_id,
                    "is_duplicate": row.is_duplicate,
                    "result_source": row.result_source,
                    "funnel_outcome": row.funnel_outcome,
                    "no_data_reason": row.no_data_reason,
                    "funnel_exit_event_id": row.funnel_exit_event_id,
                    "site_visit_outcome": row.site_visit_outcome,
                    "rule_version": OUTCOME_RULE_VERSION,
                    "computed_at": computed_at,
                }
                for row in derived.outcomes.rows
            ],
        )


def recompute_lead(
    db: Session, lead_id: int, settings: MeasurementsSettings, computed_at: datetime
) -> AttributionResult:
    """Replaces the lead's attributions and outcomes together. The caller
    commits, making it one transaction."""
    derived = compute_lead(db, lead_id, settings)
    write_lead(db, lead_id, derived, computed_at)
    return derived.attribution
