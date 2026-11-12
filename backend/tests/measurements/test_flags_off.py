"""With the module's flags off the application behaves exactly like main."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.measurements.flags import MeasurementsFlags
from tests.measurements.helpers import load_app, measurements_routes

BACKEND_DIR = Path(__file__).resolve().parents[2]
SAFE_MODULES = {"app.measurements", "app.measurements.flags", "app.measurements.models"}


@pytest.fixture(scope="module")
def disabled_app():
    return load_app(enabled=False)


@pytest.fixture(scope="module")
def on_app():
    return load_app(enabled=True)


def test_enabled_flag_defaults_to_false(monkeypatch):
    monkeypatch.delenv("MEASUREMENTS_ENABLED", raising=False)
    assert MeasurementsFlags(_env_file=None).enabled is False


def test_openapi_has_no_measurements_paths(disabled_app):
    assert not [path for path in disabled_app.openapi()["paths"] if "measurements" in path]


def test_openapi_has_no_measurements_schemas(disabled_app):
    schemas = disabled_app.openapi()["components"]["schemas"]
    assert not [name for name in schemas if "Measurements" in name]


def test_every_measurements_route_returns_404(disabled_app, on_app):
    client = TestClient(disabled_app)
    routes = measurements_routes(on_app)
    assert routes
    for path, method in routes:
        assert client.request(method, path).status_code == 404, path


def test_enabling_adds_only_measurements_paths(disabled_app, on_app):
    assert set(on_app.openapi()["paths"]) - set(disabled_app.openapi()["paths"]) == {
        path for path, _ in measurements_routes(on_app)
    }
    assert set(disabled_app.openapi()["paths"]) <= set(on_app.openapi()["paths"])


def test_disabled_app_loads_only_models_and_flags_of_the_module():
    program = (
        "import json, sys, app.main;"
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('app.measurements'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=BACKEND_DIR,
        env={**os.environ, "MEASUREMENTS_ENABLED": "false"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    assert set(json.loads(result.stdout.strip().splitlines()[-1])) == SAFE_MODULES
