"""Loads a lead's history and replaces its derived attributions (ADR-0051 §3)."""

import uuid
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
)
from app.measurements.zone import ZONE

_TASK_DEADLINE_CHANGED = "task_deadline_changed"


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


def recompute_lead(
    db: Session, lead_id: int, settings: MeasurementsSettings, computed_at: datetime
) -> AttributionResult:
    """Replaces the lead's rows. The caller commits, making it one transaction."""
    mapping = dict(
        db.execute(
            select(MeasurementsFieldValue.enum_id, MeasurementsFieldValue.visit_occurred)
        ).all()
    )
    result = attribute(
        _load_history(db, lead_id, settings),
        mapping,
        settings.cutover_at,
        ZONE,
    )

    table = MeasurementsResultAttribution.__table__
    db.execute(delete(table).where(table.c.lead_id == lead_id))
    if result.attributions:
        db.execute(
            insert(table),
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
                for row in result.attributions
            ],
        )
    return result
