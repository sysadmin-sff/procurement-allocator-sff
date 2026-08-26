from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_cors_allows_credentials_for_dev_frontend_origin():
    """Without Access-Control-Allow-Credentials: true, the browser refuses to
    expose the response (or send cookies) for a fetch(..., {credentials:
    'include'}) call from the Vite dev server origin — see ADR-0024 §7,
    frontend/src/api/client.ts. Without this, /auth/me can never succeed
    cross-origin even with valid session cookies."""
    response = client.options(
        "/auth/me",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers.get("access-control-allow-credentials") == "true"
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
