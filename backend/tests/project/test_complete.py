import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_complete_ordered_project_returns_200(db_session, make_project):
    project = make_project(status="ordered")

    response = client.post(f"/projects/{project.id}/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_complete_draft_project_returns_409(db_session, make_project):
    project = make_project(status="draft")

    response = client.post(f"/projects/{project.id}/complete")

    assert response.status_code == 409


def test_complete_calculated_project_returns_409(db_session, make_project):
    project = make_project(status="calculated")

    response = client.post(f"/projects/{project.id}/complete")

    assert response.status_code == 409


def test_complete_already_completed_project_returns_409(db_session, make_project):
    project = make_project(status="completed")

    response = client.post(f"/projects/{project.id}/complete")

    assert response.status_code == 409


def test_complete_unknown_project_returns_404():
    response = client.post(f"/projects/{uuid.uuid4()}/complete")

    assert response.status_code == 404
