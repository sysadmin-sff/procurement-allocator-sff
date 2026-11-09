"""Protection of every /measurements route (ADR-0051 criterion 3, amended 2026-11-09)."""

from datetime import datetime, timezone

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException

from app.auth.cookies import CSRF_HEADER, SESSION_COOKIE
from app.auth.dependencies import get_current_user
from app.measurements.access import require_measurements_access
from app.measurements.models import (
    MeasurementsAmoEvent,
    MeasurementsLead,
    MeasurementsSyncState,
    MeasurementsVisit,
)
from tests.measurements.helpers import assert_every_route_guarded, measurements_routes

NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


def _assert_every_route_returns(client, enabled_app, expected: int, cookie=None) -> None:
    routes = measurements_routes(enabled_app)
    assert {path for path, _ in routes} >= {"/measurements/access", "/measurements/status"}
    documented = {path for path in enabled_app.openapi()["paths"] if "measurements" in path}
    assert {path for path, _ in routes} >= documented
    client.cookies.clear()
    if cookie is not None:
        client.cookies.set(SESSION_COOKIE, str(cookie.id))
    # Every route is called before asserting, so a failure names all broken routes.
    statuses = {
        f"{method} {path}": client.request(
            method, path, headers={CSRF_HEADER: "test-csrf-token"}
        ).status_code
        for path, method in routes
    }
    assert statuses == {route: expected for route in statuses}


def _synthetic_app(*dependencies) -> FastAPI:
    router = APIRouter(prefix="/measurements", dependencies=list(dependencies))

    @router.get("/synthetic")
    def synthetic() -> dict:
        return {}

    app = FastAPI()
    app.include_router(router)
    return app


def test_every_route_has_the_guard_in_its_dependency_chain(enabled_app):
    assert_every_route_guarded(enabled_app, require_measurements_access)

    # Negative controls: the check itself must fail on an unguarded route, and
    # plain authentication is not the module's guard.
    for unguarded in (_synthetic_app(), _synthetic_app(Depends(get_current_user))):
        with pytest.raises(AssertionError, match="/measurements/synthetic"):
            assert_every_route_guarded(unguarded, require_measurements_access)

    # Positive control: the walk does see a guard placed on a router.
    assert_every_route_guarded(
        _synthetic_app(Depends(require_measurements_access)), require_measurements_access
    )


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
