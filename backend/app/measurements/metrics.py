"""Metrics of visits v1 (ADR-0053 §2, §4, §5).

Counts come from SQL over `measurements_visit_outcomes` joined to
`measurements_visits`; ratios are finished in Python with `Decimal`. The unit
is a duplicate group (§1): its first visit carries the group's outcome, the
group is completed if any of its visits is.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Date, and_, cast, distinct, func, or_, select
from sqlalchemy.orm import Session

from app.measurements.models import (
    MeasurementsSyncState,
    MeasurementsVisit,
    MeasurementsVisitOutcome,
)
from app.measurements.stale import count_stale_outcomes
from app.measurements.zone import TIMEZONE_NAME, ZONE

GROUP_BY = ("week", "month")
MAX_RANGE_DAYS = 366
VISITS_LIMIT_DEFAULT = 200
VISITS_LIMIT_MAX = 1000
_TWO_PLACES = Decimal("0.01")

_OUTCOMES = MeasurementsVisitOutcome.__table__
_VISITS = MeasurementsVisit.__table__
_DAY = _OUTCOMES.c.local_date
"""The New York day of a visit, materialized by the worker."""


class InvalidRange(ValueError):
    """Becomes a 422 in the API."""


def ratio(numerator: int, denominator: Decimal | int) -> str | None:
    if not denominator:
        return None
    value = Decimal(numerator) / Decimal(denominator)
    return str(value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))


def today_new_york(now: datetime) -> date:
    return now.astimezone(ZONE).date()


def validate_range(date_from: date, date_to: date) -> None:
    """Checked on the requested range, before alignment (§5)."""
    if date_from > date_to:
        raise InvalidRange("from is after to")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise InvalidRange(f"range is longer than {MAX_RANGE_DAYS} days")


def align(date_from: date, date_to: date, group_by: str) -> tuple[date, date]:
    if group_by == "week":
        return (
            date_from - timedelta(days=date_from.weekday()),
            date_to + timedelta(days=6 - date_to.weekday()),
        )
    if group_by == "month":
        last = monthrange(date_to.year, date_to.month)[1]
        return date_from.replace(day=1), date_to.replace(day=last)
    raise InvalidRange("group_by must be week or month")


def _next_period(start: date, group_by: str) -> date:
    if group_by == "week":
        return start + timedelta(days=7)
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1)


def periods(start: date, end: date, group_by: str) -> list[tuple[date, date]]:
    found = []
    current = start
    while current <= end:
        following = _next_period(current, group_by)
        found.append((current, following - timedelta(days=1)))
        current = following
    return found


def elapsed_days(start: date, end: date, today: date) -> int:
    """D of §2: the full length of a past period, days up to today inclusive
    for the period containing today, 0 for a future one."""
    if today > end:
        return (end - start).days + 1
    if today < start:
        return 0
    return (today - start).days + 1


@dataclass(frozen=True)
class _Columns:
    names: tuple[str, ...]
    expressions: tuple


def _aggregates(rows, now: datetime) -> _Columns:
    first = ~rows.c.is_duplicate
    funnel = rows.c.result_source == "funnel"
    site_visit = rows.c.result_source == "site_visit"
    past = rows.c.scheduled_at < now
    completed = rows.c.completed
    conducted = and_(
        first,
        completed,
        or_(
            and_(funnel, rows.c.funnel_outcome != "not_held"),
            and_(site_visit, func.coalesce(rows.c.site_visit_outcome, "") != "declined"),
        ),
    )
    planned = and_(
        first,
        ~completed,
        func.coalesce(rows.c.funnel_outcome, "") != "not_held",
        func.coalesce(rows.c.site_visit_outcome, "") != "declined",
    )
    without_result = and_(first, site_visit, rows.c.site_visit_outcome.is_(None), past)
    columns = {
        "conducted_total": func.count().filter(conducted),
        "conducted_primary": func.count().filter(and_(conducted, rows.c.kind == "primary")),
        "conducted_additional": func.count().filter(and_(conducted, rows.c.kind == "additional")),
        "conducted_legacy": func.count().filter(and_(conducted, rows.c.kind == "legacy")),
        "upcoming": func.count().filter(and_(planned, ~past)),
        "overdue": func.count().filter(and_(planned, past)),
        "visit_days": func.count(distinct(rows.c.day)).filter(conducted),
        "without_result_completed": func.count().filter(and_(without_result, completed)),
        "without_result_not_completed": func.count().filter(and_(without_result, ~completed)),
        "no_outcome": func.count().filter(
            and_(first, funnel, completed, rows.c.funnel_outcome == "no_data", past)
        ),
        "duplicates": func.count().filter(rows.c.is_duplicate),
    }
    return _Columns(tuple(columns), tuple(columns.values()))


def _rows_cte(start: date, end: date, measurer: str | None):
    group_completed = func.bool_or(_VISITS.c.is_completed).over(
        partition_by=_OUTCOMES.c.group_task_id
    )
    statement = (
        select(
            _DAY.label("day"),
            _OUTCOMES.c.measurer_key,
            _OUTCOMES.c.is_duplicate,
            _OUTCOMES.c.result_source,
            _OUTCOMES.c.funnel_outcome,
            _OUTCOMES.c.site_visit_outcome,
            _VISITS.c.kind,
            _VISITS.c.scheduled_at,
            group_completed.label("completed"),
        )
        .select_from(_OUTCOMES.join(_VISITS, _VISITS.c.task_id == _OUTCOMES.c.task_id))
        .where(_VISITS.c.deleted_at.is_(None), _DAY.between(start, end))
    )
    if measurer is not None:
        statement = statement.where(_OUTCOMES.c.measurer_key == measurer)
    return statement.cte("metric_rows")


_COMPANY = object()
"""Key of the company's block, distinct from the measurer key None."""


def _counts(
    db: Session, rows, now: datetime, group_by: str, by_period: bool, by_measurer: bool
) -> dict:
    columns = _aggregates(rows, now)
    keys = []
    if by_period:
        keys.append(cast(func.date_trunc(group_by, rows.c.day), Date).label("period"))
    if by_measurer:
        keys.append(rows.c.measurer_key)
    statement = select(*keys, *columns.expressions).select_from(rows)
    if keys:
        statement = statement.group_by(*keys)
    found = {}
    for row in db.execute(statement):
        period = row.period if by_period else None
        measurer = row.measurer_key if by_measurer else _COMPANY
        found[(period, measurer)] = dict(zip(columns.names, row[len(keys) :], strict=True))
    return found


_ZERO = {
    name: 0
    for name in (
        "conducted_total",
        "conducted_primary",
        "conducted_additional",
        "conducted_legacy",
        "upcoming",
        "overdue",
        "visit_days",
        "without_result_completed",
        "without_result_not_completed",
        "no_outcome",
        "duplicates",
    )
}


def _block(counts: dict | None, days: int) -> dict:
    counts = counts or _ZERO
    conducted = counts["conducted_total"]
    return {
        "conducted": {
            "total": conducted,
            "primary": counts["conducted_primary"],
            "additional": counts["conducted_additional"],
            "legacy": counts["conducted_legacy"],
        },
        "planned": {"upcoming": counts["upcoming"], "overdue": counts["overdue"]},
        "visit_days": counts["visit_days"],
        "per_visit_day": ratio(conducted, counts["visit_days"]),
        "per_week_avg": ratio(conducted * 7, days),
        "data_quality": {
            "without_site_visit_result": {
                "completed": counts["without_result_completed"],
                "not_completed": counts["without_result_not_completed"],
            },
            "no_outcome": counts["no_outcome"],
            "duplicates": counts["duplicates"],
        },
    }


def _measurer_order(key: str | None) -> tuple[bool, str]:
    return key is None, key or ""


def _section(counts: dict, period: date | None, measurers: list[str | None], days: int) -> dict:
    return {
        "company": _block(counts.get((period, _COMPANY)), days),
        "measurers": [
            {"measurer_key": key, **_block(counts.get((period, key)), days)} for key in measurers
        ],
    }


def data_as_of(db: Session) -> datetime | None:
    """Latest successful stream read, always in UTC: the DB session's time zone
    must not show through the API."""
    value = db.scalar(select(func.max(MeasurementsSyncState.last_success_at)))
    return None if value is None else value.astimezone(timezone.utc)


def compute_metrics(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    group_by: str,
    measurer: str | None,
    now: datetime,
) -> dict:
    validate_range(date_from, date_to)
    start, end = align(date_from, date_to, group_by)
    today = today_new_york(now)
    rows = _rows_cte(start, end, measurer)

    counts = {}
    for by_period in (True, False):
        for by_measurer in (True, False):
            counts.update(_counts(db, rows, now, group_by, by_period, by_measurer))

    if measurer is not None:
        measurers = [measurer]
    else:
        present = {key for _period, key in counts if key is not _COMPANY}
        measurers = sorted(present, key=_measurer_order)

    period_list = []
    total_days = 0
    for period_start, period_end in periods(start, end, group_by):
        days = elapsed_days(period_start, period_end, today)
        total_days += days
        period_list.append(
            {
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "days": days,
                "is_partial": period_start <= today <= period_end,
                **_section(counts, period_start, measurers, days),
            }
        )

    return {
        "timezone": TIMEZONE_NAME,
        "requested": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "from": start.isoformat(),
        "to": end.isoformat(),
        "group_by": group_by,
        "data_as_of": data_as_of(db),
        "outcomes_stale": count_stale_outcomes(db),
        "periods": period_list,
        "total": {
            "days": total_days,
            "is_partial": start <= today <= end,
            **_section(counts, None, measurers, total_days),
        },
    }


def list_visits(
    db: Session,
    *,
    date_from: date,
    date_to: date,
    measurer: str | None,
    kind: str | None,
    limit: int,
) -> list[dict]:
    """Per-visit detail without alignment. Identifiers and outcomes only (§5)."""
    validate_range(date_from, date_to)
    statement = (
        select(
            _OUTCOMES.c.task_id,
            _OUTCOMES.c.lead_id,
            _DAY.label("local_date"),
            _OUTCOMES.c.measurer_key,
            _VISITS.c.kind,
            _OUTCOMES.c.result_source,
            func.coalesce(_OUTCOMES.c.funnel_outcome, _OUTCOMES.c.site_visit_outcome).label(
                "outcome"
            ),
            _VISITS.c.is_completed,
            _OUTCOMES.c.is_duplicate,
        )
        .select_from(_OUTCOMES.join(_VISITS, _VISITS.c.task_id == _OUTCOMES.c.task_id))
        .where(_VISITS.c.deleted_at.is_(None), _DAY.between(date_from, date_to))
        .order_by(_DAY, _VISITS.c.scheduled_at, _OUTCOMES.c.task_id)
        .limit(limit)
    )
    if measurer is not None:
        statement = statement.where(_OUTCOMES.c.measurer_key == measurer)
    if kind is not None:
        statement = statement.where(_VISITS.c.kind == kind)
    return [dict(row._mapping) for row in db.execute(statement)]
