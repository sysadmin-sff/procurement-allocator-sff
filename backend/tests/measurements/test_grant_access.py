"""The grant script: dry-run by default (ADR-0051 §2, "Последствия")."""

import uuid

import pytest

from app.core.database import SessionLocal
from app.measurements.models import MeasurementsUserAccess
from app.measurements.scripts.grant_access import main
from app.models import User


@pytest.fixture
def user():
    with SessionLocal() as session:
        row = User(
            email=f"{uuid.uuid4()}@screen-factory-florida.com", role="employee", is_active=True
        )
        session.add(row)
        session.commit()
        user_id, email = row.id, row.email
    yield user_id, email
    with SessionLocal() as session:
        session.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        session.commit()


def _granted(user_id) -> bool:
    with SessionLocal() as session:
        return session.get(MeasurementsUserAccess, user_id) is not None


def _grant(user_id) -> None:
    with SessionLocal() as session:
        session.add(MeasurementsUserAccess(user_id=user_id))
        session.commit()


def test_dry_run_is_the_default_and_writes_nothing(user):
    user_id, email = user
    assert main(["--email", email]) == 0
    assert not _granted(user_id)


def test_dry_run_prints_role_and_reminder(user, capsys):
    _, email = user
    main(["--email", email])
    output = capsys.readouterr().out
    assert "role: employee" in output
    assert "DRY-RUN" in output
    assert "measurements-only" in output


def test_apply_creates_the_grant(user):
    user_id, email = user
    assert main(["--email", email, "--apply"]) == 0
    assert _granted(user_id)


def test_apply_twice_is_idempotent(user):
    user_id, email = user
    main(["--email", email, "--apply"])
    assert main(["--email", email, "--apply"]) == 0
    assert _granted(user_id)


def test_revoke_dry_run_keeps_the_grant(user):
    user_id, email = user
    _grant(user_id)
    assert main(["--email", email, "--revoke"]) == 0
    assert _granted(user_id)


def test_revoke_apply_removes_the_grant(user):
    user_id, email = user
    _grant(user_id)
    assert main(["--email", email, "--revoke", "--apply"]) == 0
    assert not _granted(user_id)


def test_unknown_email_fails_without_writing(capsys):
    assert main(["--email", "nobody@screen-factory-florida.com", "--apply"]) == 2
    assert "not found" in capsys.readouterr().err


def test_inactive_user_is_flagged(capsys):
    email = f"{uuid.uuid4()}@screen-factory-florida.com"
    with SessionLocal() as session:
        row = User(email=email, role="employee", is_active=False)
        session.add(row)
        session.commit()
        user_id = row.id
    try:
        main(["--email", email])
        assert "is_active: False" in capsys.readouterr().out
    finally:
        with SessionLocal() as session:
            session.query(User).filter(User.id == user_id).delete(synchronize_session=False)
            session.commit()
