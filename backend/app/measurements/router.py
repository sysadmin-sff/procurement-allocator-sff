from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.measurements.access import require_measurements_access
from app.measurements.models import (
    MeasurementsAmoEvent,
    MeasurementsLead,
    MeasurementsSyncState,
    MeasurementsVisit,
)
from app.measurements.stale import count_stale_outcomes

router = APIRouter(
    prefix="/measurements",
    tags=["measurements"],
    dependencies=[Depends(require_measurements_access)],
)


class MeasurementsAccessOut(BaseModel):
    access: bool


class MeasurementsStreamOut(BaseModel):
    stream: str
    watermark_at: datetime | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_status: str | None
    last_http_status: int | None
    consecutive_failures: int
    heartbeat_at: datetime | None
    counters: dict[str, int]
    """Integers only, so client data cannot reach the response through this field."""


class MeasurementsCountsOut(BaseModel):
    leads: int
    visits: int
    events: int


class MeasurementsStatusOut(BaseModel):
    last_sync_at: datetime | None
    streams: list[MeasurementsStreamOut]
    counts: MeasurementsCountsOut
    outcomes_stale: int
    """Outcome rows computed by an older rule version (ADR-0053 §3)."""


@router.get("/access", response_model=MeasurementsAccessOut)
def get_access() -> MeasurementsAccessOut:
    """Reaching this body already means access: the router dependency has passed."""
    return MeasurementsAccessOut(access=True)


@router.get("/status", response_model=MeasurementsStatusOut)
def get_status(db: Session = Depends(get_db)) -> MeasurementsStatusOut:
    streams = db.scalars(select(MeasurementsSyncState).order_by(MeasurementsSyncState.stream)).all()
    return MeasurementsStatusOut(
        last_sync_at=db.scalar(select(func.max(MeasurementsSyncState.last_success_at))),
        streams=[
            MeasurementsStreamOut(
                stream=row.stream,
                watermark_at=row.watermark_at,
                last_attempt_at=row.last_attempt_at,
                last_success_at=row.last_success_at,
                last_status=row.last_status,
                last_http_status=row.last_http_status,
                consecutive_failures=row.consecutive_failures,
                heartbeat_at=row.heartbeat_at,
                counters=row.counters,
            )
            for row in streams
        ],
        counts=MeasurementsCountsOut(
            leads=db.scalar(
                select(func.count())
                .select_from(MeasurementsLead)
                .where(MeasurementsLead.deleted_at.is_(None))
            ),
            visits=db.scalar(
                select(func.count())
                .select_from(MeasurementsVisit)
                .where(MeasurementsVisit.deleted_at.is_(None))
            ),
            events=db.scalar(select(func.count()).select_from(MeasurementsAmoEvent)),
        ),
        outcomes_stale=count_stale_outcomes(db),
    )
