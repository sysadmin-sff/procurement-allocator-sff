import uuid

from fastapi.testclient import TestClient

from app.main import app

CSRF = "test-csrf-token"


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


_employee_email_counter = [0]


def _employee_client(make_user, make_session):
    _employee_email_counter[0] += 1
    email = f"employee-project-complete{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session)


def test_complete_ordered_project_returns_200(db_session, make_project, make_user, make_session):
    project = make_project(status="ordered")
    client = _employee_client(make_user, make_session)

    response = client.post(f"/projects/{project.id}/complete", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_complete_draft_project_returns_409(db_session, make_project, make_user, make_session):
    project = make_project(status="draft")
    client = _employee_client(make_user, make_session)

    response = client.post(f"/projects/{project.id}/complete", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 409


def test_complete_calculated_project_returns_409(
    db_session, make_project, make_user, make_session
):
    project = make_project(status="calculated")
    client = _employee_client(make_user, make_session)

    response = client.post(f"/projects/{project.id}/complete", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 409


def test_complete_already_completed_project_returns_409(
    db_session, make_project, make_user, make_session
):
    project = make_project(status="completed")
    client = _employee_client(make_user, make_session)

    response = client.post(f"/projects/{project.id}/complete", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 409


def test_complete_unknown_project_returns_404(make_user, make_session):
    client = _employee_client(make_user, make_session)

    response = client.post(f"/projects/{uuid.uuid4()}/complete", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 404
