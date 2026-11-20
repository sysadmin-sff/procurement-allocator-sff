"""Machine access to the daily measurements report (ADR-0058).

Outside `/measurements` on purpose: every `/measurements` route requires an
admin session (`require_measurements_access`), while this one is called by
the reporting bot with a bearer token and exposes only counts per measurer.
"""

import hmac
from datetime import date, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.measurements.daily_report import InvalidReportDate, daily_report, default_report_day
from app.measurements.router import get_now


class ReportSettings(BaseSettings):
    """Only the report token: the backend never loads the worker's amo settings."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="MEASUREMENTS_", extra="ignore")

    report_token: SecretStr | None = None
    """MEASUREMENTS_REPORT_TOKEN: unset — the integration answers 404."""


def get_report_settings() -> ReportSettings:
    return ReportSettings()


def require_report_token(
    authorization: str | None = Header(default=None),
    settings: ReportSettings = Depends(get_report_settings),
) -> None:
    expected = settings.report_token.get_secret_value() if settings.report_token else ""
    if not expected:
        raise HTTPException(status_code=404, detail="Not Found")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid report token",
            headers={"WWW-Authenticate": "Bearer"},
        )


class MeasurerCountOut(BaseModel):
    measurer_key: str | None
    conducted: int


class ReportBlockOut(BaseModel):
    conducted: int
    measurers: list[MeasurerCountOut]


class DailyReportOut(BaseModel):
    timezone: str
    date: date
    month_from: date
    month_to: date
    data_as_of: datetime | None
    day: ReportBlockOut
    month: ReportBlockOut


router = APIRouter(
    prefix="/integrations/measurements",
    tags=["integrations"],
    dependencies=[Depends(require_report_token)],
)


@router.get("/daily-report", response_model=DailyReportOut)
def get_daily_report(
    day: date | None = Query(None, alias="date"),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
) -> dict:
    """Conducted visits for a day (default: yesterday in New York) and for its
    month up to that day, company-wide and per measurer."""
    try:
        return daily_report(db, day=day or default_report_day(now), now=now)
    except InvalidReportDate as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
