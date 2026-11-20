"""Daily measurements report for the reporting bot (ADR-0058).

Values are cross-checked against `compute_metrics` on the §6 reference data,
so the report cannot drift from the «Замеры» page."""

from datetime import date, timedelta

import pytest
from pydantic import SecretStr

from app.core.database import SessionLocal
from app.measurements.daily_report import InvalidReportDate, daily_report, default_report_day
from app.measurements.metrics import compute_metrics
from app.measurements.report_router import ReportSettings, get_report_settings
from app.measurements.router import get_now
from tests.measurements.helpers import load_app
from tests.measurements.test_metrics import MATT_KEY, NAZAR, NOW, Seed, seed_reference

TOKEN = "test-report-token"
URL = "/integrations/measurements/daily-report"


@pytest.fixture
def reference(sync_tables_clean):
    with SessionLocal() as db:
        seed_reference(Seed(db))
        yield db


def _by_key(block) -> dict:
    return {m["measurer_key"]: m["conducted"] for m in block["measurers"]}


def _metrics_month(db, month_start: date, month_end: date) -> tuple[int, dict]:
    body = compute_metrics(
        db, date_from=month_start, date_to=month_end, group_by="month", measurer=None, now=NOW
    )
    total = body["total"]
    return total["company"]["conducted"]["total"], {
        m["measurer_key"]: m["conducted"]["total"] for m in total["measurers"]
    }


def test_default_day_is_yesterday_in_new_york():
    assert default_report_day(NOW) == date(2026, 11, 13)


def test_full_month_matches_the_metrics_page(reference):
    """Last day of October: the month block equals the page's October total."""
    report = daily_report(reference, day=date(2026, 10, 31), now=NOW)
    total, by_measurer = _metrics_month(reference, date(2026, 10, 1), date(2026, 10, 31))

    assert report["month_from"] == "2026-10-01"
    assert report["month"]["conducted"] == total
    assert {k: v for k, v in _by_key(report["month"]).items() if v} == {
        k: v for k, v in by_measurer.items() if v
    }


def test_month_is_the_sum_of_its_days_and_only_up_to_the_report_day(reference):
    day = date(2026, 11, 13)
    report = daily_report(reference, day=day, now=NOW)

    days = [daily_report(reference, day=date(2026, 11, d), now=NOW) for d in range(1, 14)]
    assert report["month"]["conducted"] == sum(d["day"]["conducted"] for d in days)
    for key, value in _by_key(report["month"]).items():
        assert value == sum(_by_key(d["day"]).get(key, 0) for d in days)

    # Nothing conducted after the 13th in the reference data, so the month to
    # date equals the page's whole November.
    total, _ = _metrics_month(reference, date(2026, 11, 1), date(2026, 11, 30))
    assert report["month"]["conducted"] == total


def test_day_block_lists_every_measurer_of_the_month(reference):
    report = daily_report(reference, day=date(2026, 11, 11), now=NOW)
    day_keys = [m["measurer_key"] for m in report["day"]["measurers"]]
    month_keys = [m["measurer_key"] for m in report["month"]["measurers"]]

    assert day_keys == month_keys
    assert NAZAR in month_keys and MATT_KEY in month_keys
    assert report["day"]["conducted"] == sum(_by_key(report["day"]).values())
    if None in month_keys:
        assert month_keys[-1] is None


def test_future_day_is_rejected(reference):
    with pytest.raises(InvalidReportDate):
        daily_report(reference, day=date(2026, 11, 15), now=NOW)


# --- API ---------------------------------------------------------------------


@pytest.fixture
def report_app(enabled_app):
    enabled_app.dependency_overrides[get_now] = lambda: NOW
    enabled_app.dependency_overrides[get_report_settings] = lambda: ReportSettings(
        report_token=SecretStr(TOKEN)
    )
    return enabled_app


@pytest.fixture
def api(report_app, client, sync_tables_clean):
    return client


def test_valid_token_returns_yesterday(api):
    response = api.get(URL, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["date"] == "2026-11-13"
    assert body["month_from"] == "2026-11-01"
    assert body["timezone"] == "America/New_York"
    assert set(body) == {"timezone", "date", "month_from", "month_to", "data_as_of", "day", "month"}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}, {"Authorization": "Basic x"}],
)
def test_missing_or_wrong_token_is_401(api, headers):
    assert api.get(URL, headers=headers).status_code == 401


def test_session_cookie_does_not_open_the_report(api, make_user, make_session):
    from app.auth.cookies import SESSION_COOKIE

    api.cookies.set(SESSION_COOKIE, str(make_session(make_user(role="admin")).id))
    assert api.get(URL).status_code == 401


def test_unset_token_disables_the_integration(enabled_app, client, sync_tables_clean):
    enabled_app.dependency_overrides[get_now] = lambda: NOW
    enabled_app.dependency_overrides[get_report_settings] = lambda: ReportSettings(
        report_token=None
    )
    assert client.get(URL, headers={"Authorization": "Bearer "}).status_code == 404


def test_explicit_date_and_future_date(api):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    body = api.get(URL, params={"date": "2026-10-31"}, headers=headers).json()
    assert (body["date"], body["month_from"]) == ("2026-10-31", "2026-10-01")
    tomorrow = (NOW.date() + timedelta(days=1)).isoformat()
    assert api.get(URL, params={"date": tomorrow}, headers=headers).status_code == 422


def test_route_absent_when_module_is_off():
    off = load_app(enabled=False)
    assert not any(getattr(r, "path", "").startswith("/integrations") for r in off.routes)
