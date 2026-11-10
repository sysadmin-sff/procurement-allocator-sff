"""Metrics against the reference set of ADR-0053 §6, on the test database.

"Now" is 2026-11-14 12:00 EST (a Saturday). Visits, status and field events
are inserted directly, outcomes come from `recompute_lead`, metrics from
`compute_metrics`.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.core.database import SessionLocal
from app.measurements.attribution_store import recompute_lead
from app.measurements.config import MeasurementsSettings
from app.measurements.metrics import (
    InvalidRange,
    align,
    compute_metrics,
    elapsed_days,
    list_visits,
    ratio,
    validate_range,
)
from app.measurements.models import MeasurementsAmoEvent, MeasurementsLead, MeasurementsVisit
from app.measurements.zone import ZONE

NOW = datetime(2026, 11, 14, 12, tzinfo=ZONE)
N, MATT, U = 9861902, 14156562, 55555555
NAZAR, MATT_KEY = "Nazar", "Matt Measurement"
M, Q, SALES = 8740486, 8740374, 8740490
M_STAGE, Q_STAGE, M_DELETED_STAGE = 70000001, 70000002, 77511290
TASK_TYPES = {"primary": 4410970, "additional": 4410974, "legacy": 2}
DECLINED, COMPLETED, SOLD = 627969, 627965, 627967
L22, L26 = 1022, 1026
SETTINGS = MeasurementsSettings(_env_file=None, excluded_lead_ids=frozenset({L22}))


def ny(month, day, hour=10, minute=0, second=0, year=2026) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=ZONE)


def utc(month, day, hour, minute=0, year=2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class Seed:
    def __init__(self, db):
        self.db = db
        self.leads: set[int] = set()
        self._event = 0

    def lead(self, lead_id, deleted=False) -> None:
        self.leads.add(lead_id)
        self.db.add(
            MeasurementsLead(
                lead_id=lead_id,
                amo_updated_at=NOW,
                deleted_at=NOW if deleted else None,
                synced_at=NOW,
            )
        )

    def visit(
        self, lead_id, number, kind, who, when, completed=True, deleted_reason=None, all_day=False
    ):
        if lead_id not in self.leads:
            self.lead(lead_id)
        self.db.add(
            MeasurementsVisit(
                task_id=lead_id * 10 + number,
                lead_id=lead_id,
                task_type_id=TASK_TYPES[kind],
                kind=kind,
                responsible_amo_user_id=who,
                scheduled_at=when,
                duration=0 if all_day else 3600,
                is_all_day=all_day,
                is_completed=completed,
                result_text="CLIENT-PRIVATE-NOTE",
                amo_created_at=when,
                amo_updated_at=when,
                deleted_at=NOW if deleted_reason else None,
                deleted_reason=deleted_reason,
                synced_at=NOW,
            )
        )

    def _add_event(self, lead_id, when, event_type, before, after) -> None:
        self._event += 1
        self.db.add(
            MeasurementsAmoEvent(
                event_id=f"ev{self._event:04d}",
                event_type=event_type,
                entity_type="lead",
                entity_id=lead_id,
                lead_id=lead_id,
                occurred_at=when,
                value_before=before,
                value_after=after,
                ingested_at=NOW,
            )
        )

    def status(self, lead_id, when, after, before=(M, M_STAGE)) -> None:
        def side(value):
            return [{"lead_status": {"pipeline_id": value[0], "id": value[1]}}]

        self._add_event(lead_id, when, "lead_status_changed", side(before), side(after))

    def result(self, lead_id, when, enum_id) -> None:
        after = [{"custom_field_value": {"enum_id": enum_id}}]
        self._add_event(lead_id, when, "custom_field_784029_value_changed", [], after)

    def recompute(self) -> None:
        self.db.flush()
        for lead_id in sorted(self.leads):
            recompute_lead(self.db, lead_id, SETTINGS, NOW)
        self.db.commit()


def seed_reference(seed: Seed) -> None:
    """The §6 table, one lead per row, ids 1001..1026."""
    s = seed
    s.visit(1001, 1, "legacy", N, ny(9, 28))
    s.status(1001, ny(9, 28, 18), (M, 142))
    s.visit(1002, 1, "legacy", N, ny(9, 27, 16))
    s.status(1002, ny(9, 27, 14), (Q, Q_STAGE))
    s.status(1002, ny(9, 27, 14, 0, 1), (M, M_STAGE), before=(Q, Q_STAGE))
    s.visit(1003, 1, "legacy", N, ny(9, 30))
    s.visit(1003, 2, "legacy", MATT, ny(10, 1))
    s.status(1003, ny(9, 30, 12), (Q, Q_STAGE))
    s.status(1003, ny(10, 3), (M, 143))
    s.visit(1004, 1, "legacy", MATT, utc(11, 1, 3, 30))
    s.status(1004, ny(11, 2), (M, 142))
    s.status(1004, ny(11, 2, 10, 5), (SALES, 1), before=(M, 142))
    s.visit(1005, 1, "legacy", N, utc(11, 1, 6, 30))
    s.visit(1006, 1, "legacy", N, ny(10, 15))
    s.status(1006, ny(10, 14), (M, 142))
    s.visit(1007, 1, "legacy", N, ny(10, 20, 10))
    s.visit(1007, 2, "legacy", N, ny(10, 20, 14))
    s.status(1007, ny(10, 20, 16), (M, 142))
    s.visit(1008, 1, "legacy", N, ny(10, 21), completed=False)
    s.visit(1009, 1, "legacy", N, ny(10, 22), deleted_reason="deleted")
    s.visit(1009, 2, "legacy", N, ny(10, 23), deleted_reason="retyped")
    s.visit(1010, 1, "legacy", MATT, ny(10, 5))
    s.status(1010, ny(10, 5, 12), (M, 142))
    s.visit(1011, 1, "legacy", N, ny(11, 10))
    s.visit(1012, 1, "primary", N, ny(11, 10))
    s.result(1012, ny(11, 10, 12), DECLINED)
    s.visit(1013, 1, "primary", MATT, ny(11, 11))
    s.result(1013, ny(11, 11, 12), COMPLETED)
    s.visit(1014, 1, "additional", MATT, ny(11, 12))
    s.result(1014, ny(11, 12, 12), SOLD)
    s.visit(1015, 1, "primary", U, ny(11, 12))
    s.visit(1016, 1, "primary", N, ny(11, 20), completed=False)
    s.visit(1017, 1, "primary", MATT, ny(11, 13, 23, 59), all_day=True)
    s.result(1017, ny(11, 13, 20), COMPLETED)
    s.visit(1018, 1, "legacy", N, utc(3, 9, 3, 30))
    s.status(1018, ny(3, 9, 12), (M, 142))
    s.visit(1019, 1, "legacy", N, ny(10, 7))
    s.status(1019, ny(10, 7, 12), (M, M_DELETED_STAGE))
    s.status(1019, ny(10, 8), (M, 143), before=(M, M_DELETED_STAGE))
    s.visit(1021, 1, "legacy", N, ny(10, 12))
    s.visit(1021, 2, "legacy", N, ny(10, 14))
    s.status(1021, ny(10, 14, 12), (M, 142))
    s.visit(L22, 1, "legacy", N, ny(10, 16))
    s.status(L22, ny(10, 16, 12), (M, 142))
    s.visit(1023, 1, "legacy", N, ny(10, 8, 9))
    s.visit(1023, 2, "legacy", MATT, ny(10, 8, 15))
    s.status(1023, ny(10, 8, 16), (M, 142))
    s.visit(1024, 1, "legacy", N, ny(10, 9))
    s.status(1024, ny(10, 9, 11), (Q, 142))
    s.status(1024, ny(10, 9, 11, 0, 1), (M, M_STAGE), before=(Q, 142))
    s.status(1024, ny(10, 10), (M, 143))
    s.visit(1025, 1, "legacy", MATT, ny(10, 13))
    s.status(1025, ny(10, 13, 11), (Q, 142))
    s.status(1025, ny(10, 16), (M, M_STAGE), before=(Q, 142))
    s.lead(L26, deleted=True)
    s.visit(L26, 1, "legacy", N, ny(10, 17))
    s.status(L26, ny(10, 17, 12), (M, 142))
    s.recompute()


@pytest.fixture
def db(sync_tables_clean):
    with SessionLocal() as session:
        yield session


@pytest.fixture
def reference(db):
    seed_reference(Seed(db))
    return db


def metrics(db, date_from, date_to, group_by="month", measurer=None) -> dict:
    return compute_metrics(
        db,
        date_from=date_from,
        date_to=date_to,
        group_by=group_by,
        measurer=measurer,
        now=NOW,
    )


def by_key(section) -> dict:
    found = {"company": section["company"]}
    found.update({item["measurer_key"]: item for item in section["measurers"]})
    return found


def core(block) -> tuple:
    """(M1, M3, M4, M5)."""
    return (
        block["conducted"]["total"],
        block["visit_days"],
        block["per_visit_day"],
        block["per_week_avg"],
    )


# --- October, one month


def test_october_month(reference):
    body = metrics(reference, date(2026, 10, 1), date(2026, 10, 31))
    assert (body["from"], body["to"]) == ("2026-10-01", "2026-10-31")
    [period] = body["periods"]
    assert (period["days"], period["is_partial"]) == (31, False)
    blocks = by_key(period)
    assert [item["measurer_key"] for item in period["measurers"]] == [MATT_KEY, NAZAR]
    assert core(blocks[NAZAR]) == (7, 7, "1.00", "1.58")
    assert core(blocks[MATT_KEY]) == (4, 4, "1.00", "0.90")
    assert core(blocks["company"]) == (11, 10, "1.10", "2.48")
    for key, overdue, no_outcome, duplicates in (
        (NAZAR, 1, 2, 1),
        (MATT_KEY, 0, 0, 0),
        ("company", 1, 2, 1),
    ):
        block = blocks[key]
        assert block["planned"]["overdue"] == overdue, key
        assert block["data_quality"]["no_outcome"] == no_outcome, key
        assert block["data_quality"]["duplicates"] == duplicates, key
    assert blocks["company"]["conducted"] == {
        "total": 11,
        "primary": 0,
        "additional": 0,
        "legacy": 11,
    }


def test_company_visit_days_are_distinct_dates_not_a_sum(reference):
    [period] = metrics(reference, date(2026, 10, 1), date(2026, 10, 31))["periods"]
    blocks = by_key(period)
    # 08.10 is a visit day of both measurers (L23).
    assert blocks[NAZAR]["visit_days"] + blocks[MATT_KEY]["visit_days"] == 11
    assert blocks["company"]["visit_days"] == 10


# --- October, weeks


def test_october_weeks(reference):
    body = metrics(reference, date(2026, 10, 1), date(2026, 10, 31), "week")
    assert (body["from"], body["to"]) == ("2026-09-28", "2026-11-01")
    assert body["requested"] == {"from": "2026-10-01", "to": "2026-10-31"}
    starts = [period["period_start"] for period in body["periods"]]
    assert starts == ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26"]
    assert {period["days"] for period in body["periods"]} == {7}
    blocks = [by_key(period) for period in body["periods"]]
    nazar = [block[NAZAR]["conducted"]["total"] for block in blocks]
    matt = [block[MATT_KEY]["conducted"]["total"] for block in blocks]
    company = [core(block["company"])[:2] for block in blocks]
    assert nazar == [1, 3, 3, 1, 1]
    assert matt == [1, 2, 0, 0, 1]
    assert company == [(2, 2), (5, 4), (3, 3), (1, 1), (2, 2)]
    assert blocks[1]["company"]["per_visit_day"] == "1.25"
    quality = [
        (
            block["company"]["planned"]["overdue"],
            block["company"]["data_quality"]["duplicates"],
            block["company"]["data_quality"]["no_outcome"],
        )
        for block in blocks
    ]
    assert quality == [(0, 0, 0), (0, 0, 0), (0, 0, 2), (1, 1, 0), (0, 0, 1)]


def test_week_before_october_has_no_conducted_visit(reference):
    [period] = metrics(reference, date(2026, 9, 21), date(2026, 9, 27), "week")["periods"]
    assert period["company"]["conducted"]["total"] == 0  # L2 is not_held


# --- 15.10–03.11 by month


def test_october_and_partial_november(reference):
    body = metrics(reference, date(2026, 10, 15), date(2026, 11, 3))
    assert (body["from"], body["to"]) == ("2026-10-01", "2026-11-30")
    october, november = body["periods"]
    assert core(by_key(october)["company"]) == (11, 10, "1.10", "2.48")
    assert (november["days"], november["is_partial"]) == (14, True)
    assert [item["measurer_key"] for item in november["measurers"]] == [MATT_KEY, NAZAR, None]
    blocks = by_key(november)
    expected = {
        NAZAR: ((2, 2, "1.00", "1.00"), 1, 1, 1),
        MATT_KEY: ((3, 3, "1.00", "1.50"), 0, 0, 0),
        None: ((1, 1, "1.00", "0.50"), 0, 1, 0),
        "company": ((6, 5, "1.20", "3.00"), 1, 2, 1),
    }
    for key, (numbers, upcoming, without_result, no_outcome) in expected.items():
        block = blocks[key]
        assert core(block) == numbers, key
        assert block["planned"]["upcoming"] == upcoming, key
        quality = block["data_quality"]
        assert quality["without_site_visit_result"]["completed"] == without_result, key
        assert quality["without_site_visit_result"]["not_completed"] == 0, key
        assert quality["no_outcome"] == no_outcome, key
    assert blocks["company"]["conducted"] == {
        "total": 6,
        "primary": 3,
        "additional": 1,
        "legacy": 2,
    }
    assert blocks[NAZAR]["conducted"]["legacy"] == 2
    assert blocks[MATT_KEY]["conducted"]["primary"] == 2
    assert blocks[MATT_KEY]["conducted"]["additional"] == 1

    total = body["total"]
    assert (total["days"], total["is_partial"]) == (45, True)
    assert core(total["company"]) == (17, 15, "1.13", "2.64")


# --- the week of the spring time change


def test_week_of_march_8_2026_holds_the_late_evening_visit(reference):
    body = metrics(reference, date(2026, 3, 2), date(2026, 3, 8), "week")
    [period] = body["periods"]
    assert by_key(period)[NAZAR]["conducted"]["total"] == 1
    [following] = metrics(reference, date(2026, 3, 9), date(2026, 3, 15), "week")["periods"]
    assert following["company"]["conducted"]["total"] == 0


# --- further rules


def test_future_period_has_no_days_and_no_weekly_average(reference):
    body = metrics(reference, date(2026, 11, 1), date(2026, 12, 31))
    november, december = body["periods"]
    assert (december["days"], december["is_partial"]) == (0, False)
    assert december["company"]["per_week_avg"] is None
    assert november["company"]["per_week_avg"] == "3.00"


def test_no_visit_days_gives_null_per_visit_day(reference):
    [period] = metrics(reference, date(2026, 9, 21), date(2026, 9, 27), "week")["periods"]
    assert period["company"]["visit_days"] == 0
    assert period["company"]["per_visit_day"] is None
    assert period["company"]["per_week_avg"] == "0.00"


def test_unknown_measurer_gives_zeros(reference):
    body = metrics(reference, date(2026, 10, 1), date(2026, 10, 31), measurer="Nobody")
    [period] = body["periods"]
    assert [item["measurer_key"] for item in period["measurers"]] == ["Nobody"]
    assert core(period["company"]) == (0, 0, None, "0.00")


def test_measurer_filter_limits_the_company_too(reference):
    [period] = metrics(reference, date(2026, 10, 1), date(2026, 10, 31), measurer=MATT_KEY)[
        "periods"
    ]
    assert core(period["company"]) == (4, 4, "1.00", "0.90")


def test_response_reports_stale_rows_and_data_as_of(reference):
    body = metrics(reference, date(2026, 10, 1), date(2026, 10, 31))
    assert body["timezone"] == "America/New_York"
    assert body["outcomes_stale"] == 0
    assert body["data_as_of"] is None


def test_declined_on_the_duplicate_keeps_the_group_out_of_m1(db):
    seed = Seed(db)
    seed.visit(2001, 1, "primary", N, ny(11, 11, 9))
    seed.visit(2001, 2, "primary", N, ny(11, 11, 15))
    seed.result(2001, ny(11, 11, 17), DECLINED)  # after both: lands on the second
    seed.recompute()
    [period] = metrics(db, date(2026, 11, 1), date(2026, 11, 30))["periods"]
    company = period["company"]
    assert company["conducted"]["total"] == 0
    assert company["planned"] == {"upcoming": 0, "overdue": 0}
    assert company["data_quality"]["duplicates"] == 1


def test_group_is_completed_when_any_visit_is(db):
    seed = Seed(db)
    seed.visit(2002, 1, "primary", N, ny(11, 11, 9), completed=False)
    seed.visit(2002, 2, "primary", N, ny(11, 11, 15))
    seed.recompute()
    [period] = metrics(db, date(2026, 11, 1), date(2026, 11, 30))["periods"]
    assert period["company"]["conducted"]["total"] == 1
    assert period["company"]["planned"]["overdue"] == 0


def test_visits_detail_has_no_client_data(reference):
    found = list_visits(
        reference,
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 31),
        measurer=None,
        kind=None,
        limit=200,
    )
    assert set(found[0]) == {
        "task_id",
        "lead_id",
        "local_date",
        "measurer_key",
        "kind",
        "result_source",
        "outcome",
        "is_completed",
        "is_duplicate",
    }
    assert {row["lead_id"] for row in found}.isdisjoint({1009, L22, L26})
    assert [row["local_date"] for row in found] == sorted(row["local_date"] for row in found)
    assert len(found) == 14


def test_visits_detail_filters_and_limit(reference):
    found = list_visits(
        reference,
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 31),
        measurer=MATT_KEY,
        kind="legacy",
        limit=2,
    )
    assert [row["task_id"] for row in found] == [10032, 10101]


# --- pure helpers


def test_rounding_is_half_up():
    assert ratio(Decimal(9), 8) == "1.13"
    assert ratio(Decimal(5), 8) == "0.63"
    assert ratio(1, 0) is None


@pytest.mark.parametrize(
    ("group_by", "requested", "aligned"),
    [
        ("week", (date(2026, 10, 1), date(2026, 10, 31)), (date(2026, 9, 28), date(2026, 11, 1))),
        ("week", (date(2026, 10, 5), date(2026, 10, 11)), (date(2026, 10, 5), date(2026, 10, 11))),
        ("month", (date(2026, 10, 15), date(2026, 11, 3)), (date(2026, 10, 1), date(2026, 11, 30))),
        ("month", (date(2028, 2, 3), date(2028, 2, 3)), (date(2028, 2, 1), date(2028, 2, 29))),
    ],
)
def test_alignment(group_by, requested, aligned):
    assert align(*requested, group_by) == aligned


def test_range_checks():
    validate_range(date(2026, 1, 1), date(2027, 1, 1))  # 366 days
    with pytest.raises(InvalidRange):
        validate_range(date(2026, 1, 1), date(2027, 1, 2))
    with pytest.raises(InvalidRange):
        validate_range(date(2026, 1, 2), date(2026, 1, 1))
    with pytest.raises(InvalidRange):
        align(date(2026, 1, 1), date(2026, 1, 2), "day")


def test_elapsed_days():
    start, end = date(2026, 11, 1), date(2026, 11, 30)
    assert elapsed_days(start, end, date(2026, 12, 1)) == 30
    assert elapsed_days(start, end, date(2026, 11, 14)) == 14
    assert elapsed_days(start, end, date(2026, 11, 1)) == 1
    assert elapsed_days(start, end, date(2026, 10, 31)) == 0
