"""Outcome rows computed by an older rule version (ADR-0053 §3, criterion 4 of §3)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.measurements.models import MeasurementsVisitOutcome
from app.measurements.outcomes import OUTCOME_RULE_VERSION


def count_stale_outcomes(db: Session) -> int:
    return db.scalar(
        select(func.count())
        .select_from(MeasurementsVisitOutcome)
        .where(MeasurementsVisitOutcome.rule_version < OUTCOME_RULE_VERSION)
    )
