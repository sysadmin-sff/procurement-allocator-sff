"""Daily measurements report for the company reporting bot (ADR-0058).

Reuses the rows and counting rules of the «Замеры» page (`metrics`), so
"conducted" here is exactly `conducted.total` of `/measurements/metrics`.
"""

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.measurements import metrics
from app.measurements.zone import TIMEZONE_NAME


class InvalidReportDate(ValueError):
    """Becomes a 422 in the API."""


def default_report_day(now: datetime) -> date:
    """Yesterday in New York: the bot sends the report in the morning."""
    return metrics.today_new_york(now) - timedelta(days=1)


def _conducted(db: Session, start: date, end: date, now: datetime) -> tuple[int, dict]:
    rows = metrics._rows_cte(start, end, None)
    company = metrics._counts(db, rows, now, "month", by_period=False, by_measurer=False)
    measurers = metrics._counts(db, rows, now, "month", by_period=False, by_measurer=True)
    total = company.get((None, metrics._COMPANY), {}).get("conducted_total", 0)
    by_measurer = {key: counts["conducted_total"] for (_period, key), counts in measurers.items()}
    return total, by_measurer


def daily_report(db: Session, *, day: date, now: datetime) -> dict:
    if day > metrics.today_new_york(now):
        raise InvalidReportDate("date is in the future")
    month_start = day.replace(day=1)

    day_total, day_by = _conducted(db, day, day, now)
    month_total, month_by = _conducted(db, month_start, day, now)
    keys = sorted(set(month_by) | set(day_by), key=metrics._measurer_order)

    return {
        "timezone": TIMEZONE_NAME,
        "date": day.isoformat(),
        "month_from": month_start.isoformat(),
        "month_to": day.isoformat(),
        "data_as_of": metrics.data_as_of(db),
        "day": {
            "conducted": day_total,
            "measurers": [{"measurer_key": k, "conducted": day_by.get(k, 0)} for k in keys],
        },
        "month": {
            "conducted": month_total,
            "measurers": [{"measurer_key": k, "conducted": month_by.get(k, 0)} for k in keys],
        },
    }
