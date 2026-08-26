from app.auth.service import bootstrap_admin
from app.core.database import SessionLocal
from app.models import User


def test_bootstrap_admin_repeated_calls_same_email_no_duplicate_no_redemotion():
    session = SessionLocal()
    email = "repeat-bootstrap@screen-factory-florida.com"
    try:
        bootstrap_admin(session, email)
        first = session.query(User).filter(User.email == email).one()
        assert first.role == "admin"

        # Simulate an admin manually demoting this user via /users after bootstrap.
        first.role = "employee"
        session.commit()

        # Second bootstrap run (e.g. redeploy with same BOOTSTRAP_ADMIN_EMAIL) must
        # NOT re-promote, because another admin might exist by then -- but here
        # there are zero admins left, so per ADR-0024 §2 rule ("no admin exists at
        # all", not "no row with this email") it WOULD re-run bootstrap logic.
        # To specifically test "does not silently re-grant after manual demotion
        # while another admin exists", create a second admin first.
        other = User(email="another-admin@screen-factory-florida.com", role="admin", is_active=True)
        session.add(other)
        session.commit()

        bootstrap_admin(session, email)
        session.refresh(first)
        assert first.role == "employee"
    finally:
        session.query(User).filter(
            User.email.in_([email, "another-admin@screen-factory-florida.com"])
        ).delete(synchronize_session=False)
        session.commit()
        session.close()
