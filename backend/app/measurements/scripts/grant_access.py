"""Grants or revokes access to the measurements module. Dry-run by default.

python -m app.measurements.scripts.grant_access --email a@b.c [--revoke] [--apply]
"""

import argparse
import sys

from app.core.database import SessionLocal
from app.measurements.models import MeasurementsUserAccess
from app.models import User

REMINDER = (
    "Reminder (ADR-0051, consequences): do not grant access to measurements-only users "
    "(lead managers, surveyors and others). Any grantee also keeps the procurement routers "
    "guarded only by get_current_user until a separate ADR restricts them."
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--revoke", action="store_true")
    parser.add_argument("--apply", action="store_true", help="write the change (default: dry-run)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == args.email).one_or_none()
        if user is None:
            print(f"User not found: {args.email}", file=sys.stderr)
            return 2

        grant = db.get(MeasurementsUserAccess, user.id)
        print(f"email: {user.email}")
        print(f"role: {user.role}")
        print(f"is_active: {user.is_active}")
        print(f"current grant: {'yes' if grant else 'no'}")
        if user.role == "admin":
            print("note: admin has access without a grant")
        print(REMINDER)
        print(f"action: {'revoke' if args.revoke else 'grant'}")

        if not args.apply:
            print("DRY-RUN: nothing written, re-run with --apply")
            return 0

        if args.revoke and grant is not None:
            db.delete(grant)
        elif not args.revoke and grant is None:
            db.add(MeasurementsUserAccess(user_id=user.id))
        db.commit()
        print("APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
