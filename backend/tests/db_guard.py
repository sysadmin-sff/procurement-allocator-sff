"""Decides whether pytest may run against a database URL (ADR-0052).

Parses the URL only and never connects. Imports nothing from `app`, because
importing `app.core.database` creates the engine from `DATABASE_URL`.
"""

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

REQUIRED_SUFFIX = "_test"
# libpq and psycopg let these query parameters replace the database named in
# the path, so `.../x_test?dbname=prod` would pass a path-only check.
_DATABASE_OVERRIDE_PARAMS = ("dbname", "database", "service")


class UnsafeTestDatabaseError(Exception):
    """The URL must not be used by the test suite. The message never holds it."""


def require_test_database_url(raw_url: str | None) -> str:
    """Returns `raw_url` if it names a `*_test` database, otherwise raises."""
    if not raw_url:
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL is not set; see backend/README.md (ADR-0052)."
        )
    try:
        url = make_url(raw_url)
    except ArgumentError as exc:
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL cannot be parsed.") from exc

    overrides = [name for name in _DATABASE_OVERRIDE_PARAMS if name in url.query]
    if overrides:
        raise UnsafeTestDatabaseError(
            f"TEST_DATABASE_URL must not set {', '.join(overrides)} in its query."
        )
    if not url.database or not url.database.endswith(REQUIRED_SUFFIX):
        raise UnsafeTestDatabaseError(
            f"Refusing to run: database {url.database!r} does not end in "
            f"{REQUIRED_SUFFIX!r} (ADR-0052)."
        )
    return raw_url
