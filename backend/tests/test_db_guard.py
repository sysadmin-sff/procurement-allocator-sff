"""The guard that keeps pytest away from real databases (ADR-0052)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.db_guard import UnsafeTestDatabaseError, require_test_database_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
# Port 1 refuses connections, so an attempt to connect could not go unnoticed.
UNREACHABLE = "postgresql+psycopg://user:secret-password@127.0.0.1:1"

# Runs pytest in a fresh interpreter and reports whether `app`, which creates
# the engine on import, was ever imported.
INNER_PYTEST = """
import sys
import pytest
code = pytest.main(["tests/test_health.py", "-q", "-p", "no:cacheprovider"])
print("APP_IMPORTED=" + str("app" in sys.modules))
sys.exit(code)
"""


@pytest.mark.parametrize(
    "url",
    [
        f"{UNREACHABLE}/procurement_allocator_test",
        f"{UNREACHABLE}/anything_test?sslmode=disable",
    ],
)
def test_accepts_database_names_ending_in_test(url):
    assert require_test_database_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "not a url",
        UNREACHABLE,
        f"{UNREACHABLE}/procurement-allocator",
        f"{UNREACHABLE}/procurement_prodcopy",
        f"{UNREACHABLE}/test_procurement",
        f"{UNREACHABLE}/procurement_TEST",
        f"{UNREACHABLE}/procurement_allocator_test?dbname=procurement_prodcopy",
        f"{UNREACHABLE}/procurement_allocator_test?service=prod",
    ],
)
def test_rejects_every_other_url(url):
    with pytest.raises(UnsafeTestDatabaseError):
        require_test_database_url(url)


def test_error_message_does_not_contain_the_password():
    with pytest.raises(UnsafeTestDatabaseError) as raised:
        require_test_database_url(f"{UNREACHABLE}/procurement_prodcopy")

    assert "secret-password" not in str(raised.value)


def _run_inner_pytest(test_database_url: str | None) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": f"{UNREACHABLE}/procurement_prodcopy"}
    env.pop("TEST_DATABASE_URL", None)
    if test_database_url is not None:
        env["TEST_DATABASE_URL"] = test_database_url
    return subprocess.run(
        [sys.executable, "-c", INNER_PYTEST],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


@pytest.mark.parametrize(
    ("test_database_url", "expected_message"),
    [
        (None, "TEST_DATABASE_URL is not set"),
        (f"{UNREACHABLE}/procurement_prodcopy", "does not end in '_test'"),
    ],
)
def test_pytest_stops_before_any_connection(test_database_url, expected_message):
    result = _run_inner_pytest(test_database_url)
    output = result.stdout + result.stderr

    assert result.returncode == pytest.ExitCode.USAGE_ERROR, output
    assert expected_message in output
    assert "APP_IMPORTED=False" in output
    assert "refused" not in output.lower()
    assert "secret-password" not in output
