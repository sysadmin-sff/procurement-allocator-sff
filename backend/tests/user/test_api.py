from fastapi.testclient import TestClient

from app.main import app


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def test_list_users_requires_admin(make_user, make_session):
    employee = make_user(role="employee")
    employee_session = make_session(employee)
    client = _client_as(employee_session)
    response = client.get("/users")
    assert response.status_code == 403


def test_list_users_as_admin_succeeds(make_user, make_session):
    admin = make_user(email="admin1@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin)
    client = _client_as(admin_session)
    response = client.get("/users")
    assert response.status_code == 200
    emails = [u["email"] for u in response.json()]
    assert "admin1@screen-factory-florida.com" in emails


def test_list_users_no_session_returns_401():
    client = TestClient(app)
    response = client.get("/users")
    assert response.status_code == 401


def test_create_user_as_admin(make_user, make_session, db_session):
    admin = make_user(email="admin2@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin, csrf_token="csrf-create")
    client = _client_as(admin_session)
    response = client.post(
        "/users",
        json={"email": "new-hire@screen-factory-florida.com", "role": "employee"},
        headers={"X-CSRF-Token": "csrf-create"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new-hire@screen-factory-florida.com"
    assert body["is_active"] is True

    db, ids = db_session
    from app.models import User

    created = db.query(User).filter(User.email == "new-hire@screen-factory-florida.com").one()
    ids.append(created.id)


def test_create_user_without_csrf_header_returns_403(make_user, make_session):
    admin = make_user(email="admin3@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin, csrf_token="csrf-create2")
    client = _client_as(admin_session)
    response = client.post(
        "/users", json={"email": "blocked@screen-factory-florida.com", "role": "employee"}
    )
    assert response.status_code == 403


def test_patch_user_role_as_admin(make_user, make_session):
    admin = make_user(email="admin4@screen-factory-florida.com", role="admin")
    target = make_user(email="promote-target@screen-factory-florida.com", role="employee")
    admin_session = make_session(admin, csrf_token="csrf-patch")
    client = _client_as(admin_session)
    response = client.patch(
        f"/users/{target.id}", json={"role": "admin"}, headers={"X-CSRF-Token": "csrf-patch"}
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_patch_as_employee_returns_403(make_user, make_session):
    employee = make_user(role="employee")
    target = make_user(email="target2@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token="csrf-emp")
    client = _client_as(employee_session)
    response = client.patch(
        f"/users/{target.id}", json={"role": "admin"}, headers={"X-CSRF-Token": "csrf-emp"}
    )
    assert response.status_code == 403


def test_self_deactivation_of_last_active_admin_returns_409(make_user, make_session):
    admin = make_user(email="lonely-admin@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin, csrf_token="csrf-self")
    client = _client_as(admin_session)
    response = client.patch(
        f"/users/{admin.id}", json={"is_active": False}, headers={"X-CSRF-Token": "csrf-self"}
    )
    assert response.status_code == 409


def test_self_deactivation_when_another_admin_exists_succeeds(make_user, make_session):
    admin = make_user(email="admin-a@screen-factory-florida.com", role="admin")
    make_user(email="admin-b@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin, csrf_token="csrf-self2")
    client = _client_as(admin_session)
    response = client.patch(
        f"/users/{admin.id}", json={"is_active": False}, headers={"X-CSRF-Token": "csrf-self2"}
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False
