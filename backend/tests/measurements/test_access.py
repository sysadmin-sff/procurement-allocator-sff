"""Protection of every /measurements route (ADR-0051 criterion 3, amended 2026-11-09)."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.auth.cookies import CSRF_HEADER, SESSION_COOKIE
from app.measurements.access import require_measurements_access
from app.measurements.models import (
    MeasurementsAmoEvent,
    MeasurementsLead,
    MeasurementsSyncState,
    MeasurementsVisit,
)
from tests.measurements.helpers import measurements_routes

NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


def _assert_every_route_returns(client, enabled_app, expected: int, cookie=None) -> None:
    routes = measurements_routes(enabled_app)
    assert {path for path, _ in routes} >= {"/measurements/access", "/measurements/status"}
    documented = {path for path in enabled_app.openapi()["paths"] if "measurements" in path}
    assert {path for path, _ in routes} >= documented
    client.cookies.clear()
    if cookie is not None:
        client.cookies.set(SESSION_COOKIE, str(cookie.id))
    for path, method in routes:
        response = client.request(method, path, headers={CSRF_HEADER: "test-csrf-token"})
        assert response.status_code == expected, f"{method} {path}"


def test_without_session_every_route_returns_401(client, enabled_app):
    _assert_every_route_returns(client, enabled_app, 401)


def test_employee_without_grant_gets_403(client, enabled_app, make_user, make_session):
    _assert_every_route_returns(client, enabled_app, 403, make_session(make_user()))


def test_employee_with_grant_gets_200(client, enabled_app, make_user, make_session):
    _assert_every_route_returns(client, enabled_app, 200, make_session(make_user(granted=True)))


def test_admin_without_grant_gets_200(client, enabled_app, make_user, make_session):
    _assert_every_route_returns(client, enabled_app, 200, make_session(make_user(role="admin")))


@pytest.mark.parametrize("role", ["employee", "admin"])
def test_deactivated_user_with_live_session_gets_401(
    client, enabled_app, make_user, make_session, role
):
    user = make_user(role=role, is_active=False, granted=True)
    _assert_every_route_returns(client, enabled_app, 401, make_session(user))


@pytest.mark.parametrize("role", ["employee", "admin"])
def test_dependency_itself_rejects_an_inactive_user(db_session, make_user, role):
    session, _ = db_session
    user = make_user(role=role, is_active=False, granted=True)
    with pytest.raises(HTTPException) as exc_info:
        require_measurements_access(user=user, db=session)
    assert exc_info.value.status_code == 403


def test_access_endpoint_reports_access(client, make_user, make_session):
    client.cookies.set(SESSION_COOKIE, str(make_session(make_user(role="admin")).id))
    assert client.get("/measurements/access").json() == {"access": True}


def _seed_status_rows(session) -> None:
    session.add(MeasurementsLead(lead_id=1, synced_at=NOW))
    session.add(
        MeasurementsVisit(
            task_id=10,
            lead_id=1,
            task_type_id=4410970,
            kind="primary",
            responsible_amo_user_id=9861902,
            scheduled_at=NOW,
            is_all_day=False,
            is_completed=True,
            result_text="CLIENT-PRIVATE-NOTE",
            amo_created_at=NOW,
            amo_updated_at=NOW,
            synced_at=NOW,
        )
    )
    session.add(
        MeasurementsAmoEvent(
            event_id="evt-1",
            event_type="task_completed",
            entity_type="task",
            entity_id=10,
            lead_id=1,
            occurred_at=NOW,
            ingested_at=NOW,
        )
    )
    session.add(
        MeasurementsSyncState(
            stream="tasks",
            last_success_at=NOW,
            last_status="ok",
            last_http_status=200,
            counters={"unmapped": 2},
        )
    )
    session.flush()


def test_status_reports_streams_and_counts(client, db_session, make_user, make_session):
    session, _ = db_session
    _seed_status_rows(session)
    client.cookies.set(SESSION_COOKIE, str(make_session(make_user(role="admin")).id))

    body = client.get("/measurements/status").json()

    assert body["last_sync_at"] == "2026-11-10T12:00:00Z"
    assert body["counts"] == {"leads": 1, "visits": 1, "events": 1}
    [stream] = body["streams"]
    assert stream["stream"] == "tasks"
    assert stream["last_status"] == "ok"
    assert stream["counters"] == {"unmapped": 2}


def test_status_never_returns_result_text(client, db_session, make_user, make_session):
    session, _ = db_session
    _seed_status_rows(session)
    client.cookies.set(SESSION_COOKIE, str(make_session(make_user(role="admin")).id))

    raw = client.get("/measurements/status").text

    assert "CLIENT-PRIVATE-NOTE" not in raw
    assert "result_text" not in raw


def test_status_with_no_sync_yet(client, make_user, make_session):
    client.cookies.set(SESSION_COOKIE, str(make_session(make_user(role="admin")).id))
    body = client.get("/measurements/status").json()
    assert body["last_sync_at"] is None
    assert body["streams"] == []
    assert body["counts"] == {"leads": 0, "visits": 0, "events": 0}
