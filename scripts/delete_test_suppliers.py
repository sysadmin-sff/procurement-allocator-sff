"""One-off cleanup script: delete the "Test Supplier" rows left over from
manual QA (see docs/decisions/0028-strict-category-supplier-grouping.md
visual checks) from the running backend's supplier directory.

Safe-by-construction, not "delete everything and hope": for each supplier
named exactly "Test Supplier", this only deletes its *open* (non-historical)
Price rows, then tries DELETE /suppliers/{id}. It never touches a closed
Price (valid_to set — DELETE /prices/{id} itself refuses those, 409, by
design: closed rows are history) and never touches Order/AllocationLine —
if the supplier delete still 409s after clearing open prices, that means
something with real history (an Order, a closed Price, an AllocationLine)
references it, and the script stops and reports it instead of guessing.

Uses the running backend's own admin-only API (session-cookie auth,
ADR-0024 §2/§4) — /suppliers and /prices are both require_role("admin"),
so SESSION_ID/CSRF_TOKEN must come from an admin-logged-in browser session.

Usage:
  1. Log into the app as an admin user in your browser.
  2. Open devtools → Application/Storage → Cookies → your backend origin.
  3. Copy the values of `session_id` and `csrf_token`.
  4. Run:
       pip install requests
       BACKEND_URL=http://localhost:8000 SESSION_ID=... CSRF_TOKEN=... \\
         python scripts/delete_test_suppliers.py
     Add --dry-run to only print what would happen, without deleting anything.
"""

from __future__ import annotations

import os
import sys

import requests

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
SESSION_ID = os.environ["SESSION_ID"]
CSRF_TOKEN = os.environ["CSRF_TOKEN"]
DRY_RUN = "--dry-run" in sys.argv

TARGET_NAME = "Test Supplier"


def main() -> None:
    session = requests.Session()
    session.cookies.set("session_id", SESSION_ID)
    session.cookies.set("csrf_token", CSRF_TOKEN)
    session.headers["X-CSRF-Token"] = CSRF_TOKEN

    suppliers = session.get(f"{BACKEND_URL}/suppliers").json()
    targets = [s for s in suppliers if s["name"] == TARGET_NAME]

    if not targets:
        print(f'No supplier named "{TARGET_NAME}" found — nothing to do.')
        return

    print(f'Found {len(targets)} supplier(s) named "{TARGET_NAME}":')
    for s in targets:
        print(f"  {s['id']}")

    if DRY_RUN:
        print("\n--dry-run: not deleting anything.")

    for supplier in targets:
        supplier_id = supplier["id"]
        prices = session.get(f"{BACKEND_URL}/prices", params={"supplier_id": supplier_id}).json()
        open_prices = [p for p in prices if p["valid_to"] is None]
        closed_prices = [p for p in prices if p["valid_to"] is not None]

        print(f"\n{supplier_id} ({TARGET_NAME}):")
        print(f"  {len(open_prices)} open price row(s), {len(closed_prices)} closed (historical) price row(s)")

        if closed_prices:
            print(
                "  SKIPPED: has closed/historical Price rows — these cannot be deleted via the "
                "API by design (they're kept as history) and will make the supplier delete fail "
                "too. Not touching this one."
            )
            continue

        if DRY_RUN:
            print(f"  Would delete {len(open_prices)} open price row(s), then the supplier itself.")
            continue

        failed = False
        for price in open_prices:
            resp = session.delete(f"{BACKEND_URL}/prices/{price['id']}")
            if resp.status_code >= 400:
                print(f"  FAILED to delete price {price['id']}: {resp.status_code} {resp.text}")
                failed = True
        if failed:
            print("  SKIPPED supplier delete: not all its price rows could be cleared.")
            continue

        resp = session.delete(f"{BACKEND_URL}/suppliers/{supplier_id}")
        if resp.status_code == 204:
            print("  Deleted.")
        elif resp.status_code == 409:
            print(
                "  SKIPPED: still referenced by other records after clearing open prices "
                "(likely an Order or AllocationLine) — this supplier has real history, "
                "not deleting it. Review manually if you're sure it should go."
            )
        else:
            print(f"  FAILED: {resp.status_code} {resp.text}")

    print("\nDone.")


if __name__ == "__main__":
    main()
