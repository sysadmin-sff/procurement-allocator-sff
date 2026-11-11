from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.measurements import metrics
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


# --- metrics (ADR-0053 §5)


def get_now() -> datetime:
    """Overridable in tests; the metrics depend on the current New York day."""
    return datetime.now(timezone.utc)


class MeasurementsConductedOut(BaseModel):
    total: int
    primary: int
    additional: int
    legacy: int


class MeasurementsPlannedOut(BaseModel):
    upcoming: int
    overdue: int


class MeasurementsWithoutResultOut(BaseModel):
    completed: int
    not_completed: int


class MeasurementsDataQualityOut(BaseModel):
    without_site_visit_result: MeasurementsWithoutResultOut
    no_outcome: int
    duplicates: int


class MeasurementsMetricsBlockOut(BaseModel):
    conducted: MeasurementsConductedOut
    planned: MeasurementsPlannedOut
    visit_days: int
    per_visit_day: str | None
    """Decimal with 2 places, ROUND_HALF_UP; null when there are no visit days."""
    per_week_avg: str | None
    """Decimal with 2 places, ROUND_HALF_UP; null for a period with no elapsed days."""
    data_quality: MeasurementsDataQualityOut


class MeasurementsMeasurerMetricsOut(MeasurementsMetricsBlockOut):
    measurer_key: str | None


class MeasurementsPeriodOut(BaseModel):
    period_start: date
    period_end: date
    days: int
    is_partial: bool
    company: MeasurementsMetricsBlockOut
    measurers: list[MeasurementsMeasurerMetricsOut]


class MeasurementsTotalOut(BaseModel):
    days: int
    is_partial: bool
    company: MeasurementsMetricsBlockOut
    measurers: list[MeasurementsMeasurerMetricsOut]


class MeasurementsRangeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    date_from: date = Field(alias="from")
    date_to: date = Field(alias="to")


class MeasurementsMetricsOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    timezone: str
    requested: MeasurementsRangeOut
    date_from: date = Field(alias="from")
    date_to: date = Field(alias="to")
    group_by: str
    data_as_of: datetime | None
    outcomes_stale: int
    periods: list[MeasurementsPeriodOut]
    total: MeasurementsTotalOut


class MeasurementsVisitRowOut(BaseModel):
    """Identifiers and outcomes only: no lead names, result_text or price (§5).
    `deal_number` is the amo «Deal Number» identifier (ADR-0053, 2026-11-11)."""

    task_id: int
    lead_id: int
    local_date: date
    measurer_key: str | None
    kind: str
    result_source: str
    outcome: str | None
    is_completed: bool
    is_duplicate: bool
    deal_number: str | None


def _default_range(
    date_from: date | None, date_to: date | None, now: datetime
) -> tuple[date, date]:
    today = metrics.today_new_york(now)
    return date_from or today.replace(day=1), date_to or today


def _unprocessable(exc: metrics.InvalidRange) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.get(
    "/metrics",
    response_model=MeasurementsMetricsOut,
    response_model_by_alias=True,
)
def get_metrics(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    group_by: Literal["week", "month"] = "month",
    measurer: str | None = None,
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
) -> dict:
    """Defaults: from the 1st of the current New York month to today (§5)."""
    date_from, date_to = _default_range(date_from, date_to, now)
    try:
        return metrics.compute_metrics(
            db,
            date_from=date_from,
            date_to=date_to,
            group_by=group_by,
            measurer=measurer,
            now=now,
        )
    except metrics.InvalidRange as exc:
        raise _unprocessable(exc) from exc


@router.get("/metrics/visits", response_model=list[MeasurementsVisitRowOut])
def get_metric_visits(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    measurer: str | None = None,
    kind: Literal["primary", "additional", "legacy"] | None = None,
    limit: int = Query(metrics.VISITS_LIMIT_DEFAULT, ge=1, le=metrics.VISITS_LIMIT_MAX),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
) -> list[dict]:
    """Per-visit detail; `from`/`to` are not aligned."""
    date_from, date_to = _default_range(date_from, date_to, now)
    try:
        return metrics.list_visits(
            db,
            date_from=date_from,
            date_to=date_to,
            measurer=measurer,
            kind=kind,
            limit=limit,
        )
    except metrics.InvalidRange as exc:
        raise _unprocessable(exc) from exc
