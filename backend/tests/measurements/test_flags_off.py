"""With the module's flags off the application behaves exactly like main."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_openapi_has_no_measurements_paths():
    assert not [
        path for path in client.get("/openapi.json").json()["paths"] if "measurements" in path
    ]


def test_measurements_paths_return_404():
    for path in ("/measurements", "/measurements/access", "/measurements/status"):
        assert client.get(path).status_code == 404
