"""GET /measurements/metrics and /metrics/visits (ADR-0053 §5)."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, update

from app.auth.cookies import SESSION_COOKIE
from app.core.database import SessionLocal
from app.measurements.models import MeasurementsLead, MeasurementsSyncState
from app.measurements.router import get_now
from tests.measurements.helpers import load_app
from tests.measurements.test_metrics import MATT_KEY, NAZAR, NOW, Seed, seed_reference

FORBIDDEN_KEY_PARTS = ("result_text", "name", "price")


@pytest.fixture
def api(sync_tables_clean, client, enabled_app, make_user, make_session):
    enabled_app.dependency_overrides[get_now] = lambda: NOW
    client.cookies.set(SESSION_COOKIE, str(make_session(make_user(role="admin")).id))
    return client


@pytest.fixture
def seeded(api):
    with SessionLocal() as db:
        seed_reference(Seed(db))
    return api


def all_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in all_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in all_keys(item)}
    return set()


def test_all_keys_walks_nested_lists_and_dicts():
    assert all_keys({"a": [{"b": {"price": 1}}], "c": 2}) == {"a", "b", "price", "c"}


# --- defaults and plain GET


@pytest.mark.parametrize("path", ["/measurements/metrics", "/measurements/metrics/visits"])
def test_plain_get_as_admin_is_200(api, path):
    assert api.get(path).status_code == 200


def test_defaults_are_the_current_new_york_month_to_today(api):
    body = api.get("/measurements/metrics").json()
    assert body["requested"] == {"from": "2026-11-01", "to": "2026-11-14"}
    assert (body["from"], body["to"], body["group_by"]) == ("2026-11-01", "2026-11-30", "month")
    [period] = body["periods"]
    assert (period["days"], period["is_partial"]) == (14, True)
    assert body["timezone"] == "America/New_York"
    assert body["outcomes_stale"] == 0
    assert "data_as_of" in body


def test_week_alignment_and_reference_values_through_the_api(seeded):
    body = seeded.get(
        "/measurements/metrics",
        params={"from": "2026-10-01", "to": "2026-10-31", "group_by": "week"},
    ).json()
    assert body["requested"] == {"from": "2026-10-01", "to": "2026-10-31"}
    assert (body["from"], body["to"]) == ("2026-09-28", "2026-11-01")
    assert [period["company"]["conducted"]["total"] for period in body["periods"]] == [
        2,
        5,
        3,
        1,
        2,
    ]


def test_month_reference_values_through_the_api(seeded):
    body = seeded.get(
        "/measurements/metrics", params={"from": "2026-10-15", "to": "2026-11-03"}
    ).json()
    assert (body["from"], body["to"]) == ("2026-10-01", "2026-11-30")
    total = body["total"]
    assert (total["days"], total["is_partial"]) == (45, True)
    company = total["company"]
    assert (
        company["conducted"]["total"],
        company["visit_days"],
        company["per_visit_day"],
        company["per_week_avg"],
    ) == (17, 15, "1.13", "2.64")
    october = {item["measurer_key"]: item for item in body["periods"][0]["measurers"]}
    assert october[NAZAR]["per_week_avg"] == "1.58"
    assert october[MATT_KEY]["per_week_avg"] == "0.90"


def test_unknown_measurer_is_200_with_zeros(seeded):
    response = seeded.get("/measurements/metrics", params={"measurer": "Nobody"})
    assert response.status_code == 200
    [period] = response.json()["periods"]
    assert period["company"]["conducted"]["total"] == 0
    assert [item["measurer_key"] for item in period["measurers"]] == ["Nobody"]


def test_visits_detail(seeded):
    rows = seeded.get(
        "/measurements/metrics/visits",
        params={"from": "2026-10-01", "to": "2026-10-31", "measurer": MATT_KEY, "limit": 2},
    ).json()
    assert [row["task_id"] for row in rows] == [10032, 10101]
    assert rows[0] == {
        "task_id": 10032,
        "lead_id": 1003,
        "local_date": "2026-10-01",
        "measurer_key": MATT_KEY,
        "kind": "legacy",
        "result_source": "funnel",
        "outcome": "closed",
        "is_completed": True,
        "is_duplicate": False,
        "deal_number": None,
    }


def test_visits_detail_carries_the_deal_number_of_the_lead(seeded):
    with SessionLocal() as db:
        db.execute(
            update(MeasurementsLead)
            .where(MeasurementsLead.lead_id == 1003)
            .values(deal_number="SF-1003")
        )
        db.commit()
    rows = seeded.get(
        "/measurements/metrics/visits",
        params={"from": "2026-10-01", "to": "2026-10-31", "measurer": MATT_KEY, "limit": 2},
    ).json()
    assert [(row["lead_id"], row["deal_number"]) for row in rows] == [
        (1003, "SF-1003"),
        (rows[1]["lead_id"], None),
    ]


# --- 422


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/measurements/metrics", {"from": "2026-10-02", "to": "2026-10-01"}),
        ("/measurements/metrics", {"from": "2026-01-01", "to": "2027-01-02"}),
        ("/measurements/metrics", {"group_by": "day"}),
        ("/measurements/metrics", {"from": "not-a-date"}),
        ("/measurements/metrics/visits", {"from": "2026-10-02", "to": "2026-10-01"}),
        ("/measurements/metrics/visits", {"from": "2026-01-01", "to": "2027-01-02"}),
        ("/measurements/metrics/visits", {"limit": 1001}),
        ("/measurements/metrics/visits", {"limit": 0}),
        ("/measurements/metrics/visits", {"kind": "meeting"}),
    ],
)
def test_invalid_parameters_are_422(api, path, params):
    assert api.get(path, params=params).status_code == 422


def test_range_of_exactly_366_days_is_allowed(api):
    response = api.get("/measurements/metrics", params={"from": "2026-01-01", "to": "2027-01-01"})
    assert response.status_code == 200


# --- no client data


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/measurements/metrics", {"from": "2026-10-15", "to": "2026-11-03"}),
        ("/measurements/metrics", {"from": "2026-10-01", "to": "2026-10-31", "group_by": "week"}),
        ("/measurements/metrics/visits", {"from": "2026-09-01", "to": "2026-11-30", "limit": 1000}),
    ],
)
def test_responses_have_no_client_data_keys(seeded, path, params):
    response = seeded.get(path, params=params)
    assert response.status_code == 200
    keys = all_keys(response.json())
    assert keys
    assert [key for key in keys if any(part in key for part in FORBIDDEN_KEY_PARTS)] == []
    assert "CLIENT-PRIVATE-NOTE" not in response.text


# --- flag off


def test_with_the_flag_off_the_routes_do_not_exist():
    disabled = load_app(enabled=False)
    client = TestClient(disabled)
    for path in ("/measurements/metrics", "/measurements/metrics/visits"):
        assert client.get(path).status_code == 404
    assert not [path for path in disabled.openapi()["paths"] if "metrics" in path]


def test_data_as_of_is_utc_with_z_whatever_the_session_time_zone(api, db_session):
    session, _ = db_session
    session.add(
        MeasurementsSyncState(
            stream="tasks_new",
            last_success_at=datetime(2026, 11, 10, 17, 16, 50, tzinfo=timezone.utc),
        )
    )
    session.flush()
    session.execute(text("SET TIME ZONE 'Asia/Dubai'"))  # +04:00, no daylight saving
    assert session.execute(text("SELECT now()::text")).scalar().endswith("+04")
    body = api.get("/measurements/metrics").json()
    assert body["data_as_of"] == "2026-11-10T17:16:50Z"
