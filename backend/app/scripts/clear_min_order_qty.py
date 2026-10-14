"""Transactional, explicit-confirmation clearing of bad Price.min_order_qty
values found by audit_min_order_qty.py — see ADR-0045 §План выкатки п.3.

This script does NOT decide which values are garbage. It only clears the
exact Price rows it is told to, by id, inside one transaction, after
printing what it is about to change and what changed. Nothing here runs
automatically — it must be invoked explicitly, by id, after a human has
looked at the audit report and decided a given value is wrong (e.g. the
LLM extractor mistook a pallet count or an unrelated number in the price
list for min_order_qty).

Sets min_order_qty to NULL (not 0 — NULL means "no MOQ", see
docs/data-model.md) on exactly the given Price ids. Refuses to run if any
id does not match an active (valid_to IS NULL) Price row with a non-null
min_order_qty, rather than silently skipping it.

Usage (dry run — default, prints the SELECT preview, does not write):
    docker compose exec backend python -m app.scripts.clear_min_order_qty \\
        --price-id <uuid> [--price-id <uuid> ...]

Usage (actually clears, inside one transaction, with before/after SELECT):
    docker compose exec backend python -m app.scripts.clear_min_order_qty \\
        --price-id <uuid> [--price-id <uuid> ...] --confirm
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.material import Material
from app.models.price import Price
from app.models.supplier import Supplier


def _load_targets(session, price_ids: list[uuid.UUID]) -> list[Price]:
    rows = session.scalars(
        select(Price).where(Price.id.in_(price_ids), Price.valid_to.is_(None))
    ).all()
    found_ids = {row.id for row in rows}
    missing = [pid for pid in price_ids if pid not in found_ids]
    if missing:
        raise SystemExit(
            f"Refusing to proceed: {len(missing)} id(s) are not active Price rows: "
            f"{', '.join(str(m) for m in missing)}"
        )
    not_set = [row for row in rows if row.min_order_qty is None]
    if not_set:
        raise SystemExit(
            "Refusing to proceed: these Price rows already have min_order_qty "
            f"NULL, nothing to clear: {', '.join(str(r.id) for r in not_set)}"
        )
    return rows


def _verify_cleared(session, price_ids: list[uuid.UUID]) -> list[tuple[uuid.UUID, int | None]]:
    # Deliberately NOT select(Price): after flush(), the session's identity
    # map already holds these exact Price objects with min_order_qty
    # already set to None in memory -- a plain ORM select(Price) would just
    # hand back those same mutated instances without re-reading anything,
    # making the "verification" vacuous (it would pass even if the UPDATE
    # never reached the database). Selecting bare columns bypasses the
    # identity map and forces a real read of what the row currently
    # contains in this transaction. Split into its own function so a test
    # can monkeypatch just this read (simulating a failed verification)
    # without needing a hand-built fake session for the rest of main().
    return session.execute(
        select(Price.id, Price.min_order_qty).where(Price.id.in_(price_ids))
    ).all()


def _print_preview(session, rows: list[Price], label: str) -> None:
    print(f"\n{label} ({len(rows)} row(s)):")
    for row in rows:
        material = session.get(Material, row.material_id)
        supplier = session.get(Supplier, row.supplier_id)
        print(
            f"  {row.id}  {supplier.name} / {material.canonical_name} "
            f"({material.internal_sku})  min_order_qty={row.min_order_qty}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--price-id",
        dest="price_ids",
        action="append",
        required=True,
        help="Price.id to clear min_order_qty on. Repeatable.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually write the change. Without this flag, only previews.",
    )
    args = parser.parse_args()

    try:
        price_ids = [uuid.UUID(raw) for raw in args.price_ids]
    except ValueError as exc:
        raise SystemExit(f"Invalid --price-id: {exc}") from exc

    session = SessionLocal()
    try:
        targets = _load_targets(session, price_ids)
        _print_preview(session, targets, "Before (current min_order_qty)")

        if not args.confirm:
            print("\nDry run only — pass --confirm to actually clear these values.")
            return

        for row in targets:
            row.min_order_qty = None
        session.flush()

        verify_rows = _verify_cleared(session, price_ids)
        print(f"\nAfter (verification SELECT, bypassing identity map, {len(verify_rows)} row(s)):")
        for price_id, min_order_qty in verify_rows:
            print(f"  {price_id}  min_order_qty={min_order_qty}")

        still_set = [(pid, moq) for pid, moq in verify_rows if moq is not None]
        if still_set:
            session.rollback()
            raise SystemExit(
                "Verification SELECT found rows still non-null after update — "
                "rolled back, nothing committed."
            )

        session.commit()
        print(f"\nCommitted: cleared min_order_qty on {len(targets)} Price row(s).")
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
