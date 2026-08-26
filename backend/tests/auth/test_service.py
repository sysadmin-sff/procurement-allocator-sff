import time

import pytest

from app.auth.constants import SESSION_ABSOLUTE_TTL
from app.auth.google import GoogleClaims
from app.auth.service import (
    LoginRejectedError,
    bootstrap_admin,
    create_session,
    delete_session,
    get_valid_session,
    resolve_user_for_login,
    touch_session,
)

DOMAIN = "screen-factory-florida.com"


def _claims(sub="google-sub-1", email="employee@screen-factory-florida.com", hd=DOMAIN):
    return GoogleClaims(sub=sub, email=email, name="Test User", hd=hd)


def test_resolve_user_for_login_domain_mismatch(db_session):
    session, _ = db_session
    with pytest.raises(LoginRejectedError) as exc_info:
        resolve_user_for_login(session, _claims(hd="othercompany.com"), DOMAIN)
    assert exc_info.value.reason == "domain_mismatch"


def test_resolve_user_for_login_missing_hd_claim(db_session):
    session, _ = db_session
    with pytest.raises(LoginRejectedError) as exc_info:
        resolve_user_for_login(session, _claims(hd=None), DOMAIN)
    assert exc_info.value.reason == "domain_mismatch"


def test_resolve_user_for_login_sub_not_found_email_not_found(db_session):
    session, _ = db_session
    with pytest.raises(LoginRejectedError) as exc_info:
        resolve_user_for_login(
            session,
            _claims(sub="unknown-sub", email="nobody@screen-factory-florida.com"),
            DOMAIN,
        )
    assert exc_info.value.reason == "user_not_found"


def test_resolve_user_for_login_found_by_sub(db_session, make_user):
    session, _ = db_session
    user = make_user(email="employee@screen-factory-florida.com", google_sub="google-sub-1")
    resolved = resolve_user_for_login(
        session,
        _claims(sub="google-sub-1", email="employee@screen-factory-florida.com"),
        DOMAIN,
    )
    assert resolved.id == user.id


def test_resolve_user_for_login_inactive_user(db_session, make_user):
    session, _ = db_session
    make_user(
        email="employee@screen-factory-florida.com", google_sub="google-sub-1", is_active=False
    )
    with pytest.raises(LoginRejectedError) as exc_info:
        resolve_user_for_login(
            session,
            _claims(sub="google-sub-1", email="employee@screen-factory-florida.com"),
            DOMAIN,
        )
    assert exc_info.value.reason == "user_inactive"


def test_resolve_user_for_login_bootstrap_fallback_by_email_fills_sub(db_session, make_user):
    session, _ = db_session
    user = make_user(email="preexisting@screen-factory-florida.com", google_sub=None)
    resolved = resolve_user_for_login(
        session,
        _claims(sub="google-sub-new", email="preexisting@screen-factory-florida.com"),
        DOMAIN,
    )
    assert resolved.id == user.id
    assert resolved.google_sub == "google-sub-new"


def test_resolve_user_for_login_email_matches_but_sub_taken_by_someone_else(db_session, make_user):
    session, _ = db_session
    make_user(email="shared@screen-factory-florida.com", google_sub="already-someone-elses-sub")
    with pytest.raises(LoginRejectedError) as exc_info:
        resolve_user_for_login(
            session,
            _claims(sub="a-different-sub", email="shared@screen-factory-florida.com"),
            DOMAIN,
        )
    assert exc_info.value.reason == "user_not_found"


def test_create_session_sets_last_login_at(db_session, make_user):
    session, _ = db_session
    user = make_user()
    assert user.last_login_at is None
    user_session = create_session(session, user)
    session.refresh(user)
    assert user.last_login_at is not None
    assert user_session.user_id == user.id
    assert user_session.csrf_token


def test_get_valid_session_returns_none_when_idle_expired(db_session, make_user, make_session):
    session, _ = db_session
    user = make_user()
    user_session = make_session(user, expired=True)
    assert get_valid_session(session, str(user_session.id)) is None


def test_get_valid_session_returns_none_when_absolute_expired(db_session, make_user, make_session):
    session, _ = db_session
    user = make_user()
    user_session = make_session(user, absolute_expired=True)
    assert get_valid_session(session, str(user_session.id)) is None


def test_get_valid_session_returns_session_when_valid(db_session, make_user, make_session):
    session, _ = db_session
    user = make_user()
    user_session = make_session(user)
    found = get_valid_session(session, str(user_session.id))
    assert found is not None
    assert found.id == user_session.id


def test_touch_session_extends_expires_at_but_caps_at_absolute_ttl(
    db_session, make_user, make_session
):
    session, _ = db_session
    user = make_user()
    user_session = make_session(user)
    old_expires = user_session.expires_at
    # A sub-millisecond delay guards against this platform's coarse wall-clock
    # resolution making the two `utcnow()` samples (fixture setup vs.
    # touch_session's internal call) collide on the same tick, which would
    # make `>` spuriously false despite touch_session behaving correctly.
    time.sleep(0.01)
    touch_session(session, user_session)
    assert user_session.expires_at > old_expires
    assert user_session.expires_at <= user_session.created_at + SESSION_ABSOLUTE_TTL


def test_delete_session_removes_row(db_session, make_user, make_session):
    session, _ = db_session
    user = make_user()
    user_session = make_session(user)
    session_id = str(user_session.id)
    delete_session(session, session_id)
    assert get_valid_session(session, session_id) is None


def test_delete_session_nonexistent_is_noop(db_session):
    session, _ = db_session
    delete_session(session, "00000000-0000-0000-0000-000000000000")


def test_bootstrap_admin_creates_new_user_when_none_exists(db_session):
    session, user_ids = db_session
    bootstrap_admin(session, "newadmin@screen-factory-florida.com")
    from app.models import User

    user = session.query(User).filter(User.email == "newadmin@screen-factory-florida.com").one()
    user_ids.append(user.id)
    assert user.role == "admin"
    assert user.is_active is True
    assert user.google_sub is None


def test_bootstrap_admin_promotes_existing_user_by_email(db_session, make_user):
    session, _ = db_session
    user = make_user(email="promoteme@screen-factory-florida.com", role="employee")
    bootstrap_admin(session, "promoteme@screen-factory-florida.com")
    session.refresh(user)
    assert user.role == "admin"


def test_bootstrap_admin_idempotent_does_not_duplicate(db_session):
    session, user_ids = db_session
    bootstrap_admin(session, "idempotent@screen-factory-florida.com")
    bootstrap_admin(session, "idempotent@screen-factory-florida.com")
    from app.models import User

    matches = (
        session.query(User).filter(User.email == "idempotent@screen-factory-florida.com").all()
    )
    user_ids.extend(u.id for u in matches)
    assert len(matches) == 1


def test_bootstrap_admin_does_not_repromote_after_manual_demotion(db_session, make_user):
    session, _ = db_session
    make_user(email="other-admin@screen-factory-florida.com", role="admin")
    demoted = make_user(email="demoted@screen-factory-florida.com", role="employee")
    bootstrap_admin(session, "demoted@screen-factory-florida.com")
    session.refresh(demoted)
    assert demoted.role == "employee"
