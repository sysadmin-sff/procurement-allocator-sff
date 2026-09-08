"""One-off script: create project "#4665" with its BOM from the supplied
spreadsheet, matching each line to an existing Material by internal_sku
(CLAUDE.md принцип 3 — materials are identified by SKU, never by name).

Not part of the app itself — run manually, once, then discard or keep as a
reference. Uses the running backend's own API (session-cookie auth, ADR-0024
§2/§3), same as the browser does; does not touch the DB directly.

Usage:
  1. Log into the app in your browser as usual.
  2. Open devtools → Application/Storage → Cookies → your backend origin.
  3. Copy the values of `session_id` and `csrf_token`.
  4. Run:
       pip install requests
       BACKEND_URL=http://localhost:8000 SESSION_ID=... CSRF_TOKEN=... \\
         python scripts/create_project_4665.py
"""

from __future__ import annotations

import os
import sys

import requests

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
SESSION_ID = os.environ["SESSION_ID"]
CSRF_TOKEN = os.environ["CSRF_TOKEN"]

PROJECT_TITLE = "#4665"

# (internal_sku, quantity, description) — description is just for the
# printed report below, not sent to the API. See the chat conversation for
# how each ambiguous row (Bugsweep size, Downpipe length, SMB length, Flat
# Spline gauge) was resolved with the user before writing this list.
ITEMS: list[tuple[str, int, str]] = [
    ("DOOR-009", 2, '42" x 80" Door Blank with 8" Kick Plate (Bronze)'),
    ("DOOR-015", 2, "Adjustable Z-Bar x 17' (Bronze)"),
    ("DOOR-016", 6, "Hinges (Bronze)"),
    ("DOOR-019", 2, 'Bugsweep 42" (Bronze)'),
    ("DOOR-021", 2, "Eliminator Door Hardware Kit (Bronze)"),
    ("GUTR-006", 1, "7\" Super Gutter x 24' (Bronze)"),
    ("GUTR-013", 2, 'Super Gutter End Cap 7" (Bronze)'),
    ("GUTR-025", 1, 'Rain Carrying Accessories 3" x 4" Downpipe x 8\' (Bronze)'),
    ("GUTR-027", 2, "Rain Carrying Accessories (3 x 4 B Elbow) (Bronze)"),
    ("GUTR-028", 2, "Rain Carrying Accessories (3 x 4 A Elbow) (Bronze)"),
    ("GUTR-029", 1, "Rain Carrying Accessories (3 x 4 Drop Outlet)"),
    ("CAUL-002", 1, "Solar Seal Bronze"),
    ("PROF-025", 9, "2\" x 6\" SMB x 30' (Bronze)"),
    ("PROF-007", 4, "2 x 2 x .045 Patio x 30' (Bronze)"),
    ("PROF-006", 6, "2 x 2 x .045 Patio x 24' (Bronze)"),
    ("PROF-003", 5, "1 x 2 Open Back x .040 min. x 30' (Bronze)"),
    ("PROF-002", 3, "1 x 2 Open Back x .040 min. x 24' (Bronze)"),
    ("MESH-024", 2, "20/20 No See Um x 100' Rolls x 96\""),
    ("MESH-001", 1, ".310 Flat Spline x 1000'"),
    ("CONN-013", 1, "1-1/2\" x 2-1/8\" Receiving Channel x 24'"),
    ("CONN-018", 2, "Angle 2x2x.093 x 20' (Bronze)"),
    ("CONN-011", 1, "Touch Up Paint (Bronze)"),
    ("CONN-025", 1, '.187 Gusset Plate 16" x 120"'),
    ("SCRW-001", 6, '12 x 3/4" Bronze Stainless steel (100 ct)'),
    ("SCRW-004", 4, '10 x 3/4" Bronze Stainless steel (100 ct)'),
    ("SCRW-007", 2, '10 x 2" Bronze Stainless steel (100 ct)'),
    ("SCRW-012", 1, '14 x 2" Bronze Stainless steel (100 ct)'),
    ("SCRW-014", 1, '14 x 3" Bronze Stainless steel (100 ct)'),
    ("SCRW-026", 1, 'Anchor 3/8x5" Bronze Stainless steel (100 ct)'),
]


def main() -> None:
    session = requests.Session()
    session.cookies.set("session_id", SESSION_ID)
    session.cookies.set("csrf_token", CSRF_TOKEN)
    session.headers["X-CSRF-Token"] = CSRF_TOKEN

    materials = session.get(f"{BACKEND_URL}/materials").json()
    material_by_sku = {m["internal_sku"]: m for m in materials}

    missing = [sku for sku, _, _ in ITEMS if sku not in material_by_sku]
    if missing:
        print(f"ERROR: these internal_sku were not found in /materials: {missing}")
        print("The materials catalog on this backend may differ from backend/data/import/materials.csv.")
        sys.exit(1)

    project = session.post(f"{BACKEND_URL}/projects", json={"title": PROJECT_TITLE}).json()
    print(f"Created project {project['id']} \"{project['title']}\"")

    for sku, quantity, description in ITEMS:
        material = material_by_sku[sku]
        resp = session.post(
            f"{BACKEND_URL}/projects/{project['id']}/items",
            json={"material_id": material["id"], "quantity": quantity},
        )
        if resp.status_code >= 400:
            print(f"  FAILED {sku} ({description}): {resp.status_code} {resp.text}")
        else:
            print(f"  + {sku}  x{quantity}  {description}")

    print(f"\nDone: {project['id']}")


if __name__ == "__main__":
    main()
