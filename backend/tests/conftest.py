"""Points the whole suite at a disposable database (ADR-0052).

The check runs at import time because pytest imports this file before any
other conftest, and those import `app.core.database`, which builds the engine
from `DATABASE_URL`. `DATABASE_URL` therefore has to be replaced first.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tests.db_guard import UnsafeTestDatabaseError, require_test_database_url

BACKEND_DIR = Path(__file__).resolve().parents[1]

try:
    TEST_DATABASE_URL = require_test_database_url(os.environ.get("TEST_DATABASE_URL"))
except UnsafeTestDatabaseError as exc:
    # While a conftest is being imported, pytest reports this as a usage error
    # (exit code 4) whatever return code is passed here.
    pytest.exit(str(exc))

os.environ["DATABASE_URL"] = TEST_DATABASE_URL


def _recreate_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    maintenance_engine = create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    quoted_name = maintenance_engine.dialect.identifier_preparer.quote(url.database)
    try:
        with maintenance_engine.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {quoted_name} WITH (FORCE)"))
            connection.execute(text(f"CREATE DATABASE {quoted_name}"))
    finally:
        maintenance_engine.dispose()


def _apply_migrations() -> None:
    # A subprocess, because alembic's env.py reconfigures logging for the
    # process it runs in, which would break caplog in the tests.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.exit(
            f"alembic upgrade head failed:\n{result.stderr}",
            returncode=pytest.ExitCode.INTERNAL_ERROR,
        )


def pytest_sessionstart(session):
    _recreate_database()
    _apply_migrations()
