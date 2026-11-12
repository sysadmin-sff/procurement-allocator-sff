"""docker-compose.yml wiring of measurements-worker (ADR-0051 §1, §5).

Parses the file statically: env files are never read, so the checks hold
without the server-only secret file.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[3]
SECRET_FILE = "backend/.env.measurements"
MAIN_SERVICES = ("postgres", "backend", "frontend")


@pytest.fixture(scope="module")
def services() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def _env_files(service: dict) -> list[str]:
    entries = service.get("env_file") or []
    if isinstance(entries, str):
        entries = [entries]
    return [entry if isinstance(entry, str) else entry["path"] for entry in entries]


def test_worker_runs_under_its_own_profile_from_the_backend_image(services):
    worker = services["measurements-worker"]
    assert worker["profiles"] == ["measurements"]
    assert worker["build"] == services["backend"]["build"]
    assert worker["command"] == ["python", "-m", "app.measurements.worker"]
    assert worker["restart"] == "unless-stopped"


def test_only_the_worker_receives_the_secret_file(services):
    assert _env_files(services["measurements-worker"]) == ["backend/.env", SECRET_FILE]
    for name in MAIN_SERVICES:
        assert SECRET_FILE not in _env_files(services[name]), name
        environment = services[name].get("environment") or {}
        assert not [key for key in environment if str(key).startswith("MEASUREMENTS_")], name


def test_main_services_neither_depend_on_nor_share_a_profile_with_the_worker(services):
    for name in MAIN_SERVICES:
        assert "measurements-worker" not in (services[name].get("depends_on") or {}), name
        assert "profiles" not in services[name], name


def test_worker_healthcheck_and_log_rotation(services):
    worker = services["measurements-worker"]
    assert worker["healthcheck"]["test"] == ["CMD", "python", "-m", "app.measurements.healthcheck"]
    assert worker["logging"]["driver"] == "json-file"
    assert set(worker["logging"]["options"]) == {"max-size", "max-file"}
    for name in MAIN_SERVICES:
        assert "logging" not in services[name], name


def test_worker_waits_for_a_healthy_postgres(services):
    assert services["measurements-worker"]["depends_on"] == {
        "postgres": {"condition": "service_healthy"}
    }


def test_the_secret_file_is_git_ignored():
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    result = subprocess.run(
        ["git", "check-ignore", "-q", SECRET_FILE], cwd=ROOT, capture_output=True
    )
    assert result.returncode == 0


def test_the_image_never_copies_env_files():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    copies = [line for line in dockerfile.splitlines() if line.strip().startswith("COPY")]
    assert copies
    assert not [line for line in copies if ".env" in line or line.split()[1] == "."]
