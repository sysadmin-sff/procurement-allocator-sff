"""Read-only audit of Price.min_order_qty before ADR-0045 enables it in
allocation — see ADR-0045 §План выкатки п.2.

min_order_qty has existed on Price since ADR-0019 and is already extracted
by the PDF price-list parser, but nothing has ever read it in allocation —
it is inert data nobody has had a reason to double-check. Before the solver
starts treating it as a hard floor on purchase quantity, every non-null
value in prod needs a human look: a value the LLM extractor mistook for
something else (a pallet count, a different kind of multiple, a text
artifact in the price list) would silently force an inflated purchase once
this is wired in.

READ-ONLY: only SELECTs. session.commit() is never called in this file.

Usage:
    docker compose exec backend python -m app.scripts.audit_min_order_qty \\
        [--csv ./min_order_qty_audit.csv]
"""

from __future__ import annotations

import argparse
import csv
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.models.material import Material
from app.models.price import Price
from app.models.supplier import Supplier


@dataclass(frozen=True)
class MoqRow:
    price_id: uuid.UUID
    """Price.id — pass this to clear_min_order_qty.py's --price-id if this
    row's value turns out to be garbage."""
    supplier_name: str
    material_internal_sku: str
    material_canonical_name: str
    min_order_qty: int
    unit: str
    price: str
    """Price.price is NUMERIC(12,3) -- str(), not float(), to show exactly
    what is stored without binary-float rounding (this is a display-only
    report, never used for arithmetic, so there's no reason to go through
    float at all; see CLAUDE.md principle 4 on money arithmetic)."""
    currency: str
    availability: int | None
    valid_from: str
    is_active: bool
    likely_from_pdf_import: bool
    """source_import_id is not NULL — this value most likely came from the
    LLM extraction pipeline (ADR-0019), not a manual PriceForm entry. Not a
    certainty (a manually-entered value could coincidentally match one that
    was later re-imported), just a hint for where to look first."""


def collect_min_order_qty_rows(session) -> list[MoqRow]:
    # Defense in depth for a script documented as READ-ONLY: makes the
    # current transaction itself refuse any write, not just rely on this
    # file never calling session.commit(). A caller who imports this
    # function and tries to mutate something in the same session/
    # transaction gets a database-level error, not a silent write.
    session.execute(text("SET TRANSACTION READ ONLY"))

    rows = session.execute(
        select(Price, Material, Supplier)
        .join(Material, Price.material_id == Material.id)
        .join(Supplier, Price.supplier_id == Supplier.id)
        .where(Price.valid_to.is_(None), Price.min_order_qty.is_not(None))
        .order_by(Supplier.name, Material.canonical_name)
    ).all()

    return [
        MoqRow(
            price_id=price.id,
            supplier_name=supplier.name,
            material_internal_sku=material.internal_sku,
            material_canonical_name=material.canonical_name,
            min_order_qty=price.min_order_qty,
            unit=material.unit,
            price=str(price.price),
            currency=price.currency,
            availability=price.availability,
            valid_from=price.valid_from.isoformat(),
            is_active=supplier.is_active_for_allocation,
            likely_from_pdf_import=price.source_import_id is not None,
        )
        for price, material, supplier in rows
    ]


def print_report(rows: list[MoqRow]) -> None:
    if not rows:
        print("No active Price rows have a non-null min_order_qty.")
        return

    print(f"{len(rows)} active Price row(s) with min_order_qty set:\n")
    by_value_desc = sorted(rows, key=lambda r: r.min_order_qty, reverse=True)
    for row in by_value_desc:
        flags = []
        if row.min_order_qty > 1:
            flags.append("REVIEW (>1)")
        if not row.is_active:
            flags.append("supplier inactive for allocation")
        if row.likely_from_pdf_import:
            flags.append("from PDF import")
        flag_text = f"  [{', '.join(flags)}]" if flags else ""
        print(
            f"  [{row.price_id}] {row.supplier_name} / {row.material_canonical_name} "
            f"({row.material_internal_sku}): min_order_qty={row.min_order_qty} {row.unit} "
            f"@ {row.price} {row.currency}, availability={row.availability}, "
            f"valid_from={row.valid_from}{flag_text}"
        )

    review_count = sum(1 for r in rows if r.min_order_qty > 1)
    print(
        f"\n{review_count} of {len(rows)} value(s) are > 1 and need explicit "
        "manual confirmation before MOQ is enabled in allocation (ADR-0045)."
    )


def write_csv(rows: list[MoqRow], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "price_id",
                "supplier_name",
                "material_internal_sku",
                "material_canonical_name",
                "min_order_qty",
                "unit",
                "price",
                "currency",
                "availability",
                "valid_from",
                "supplier_is_active_for_allocation",
                "likely_from_pdf_import",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.price_id,
                    row.supplier_name,
                    row.material_internal_sku,
                    row.material_canonical_name,
                    row.min_order_qty,
                    row.unit,
                    row.price,
                    row.currency,
                    row.availability if row.availability is not None else "",
                    row.valid_from,
                    row.is_active,
                    row.likely_from_pdf_import,
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv", dest="csv_path", default=None, help="Optional path to also write a CSV report."
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        rows = collect_min_order_qty_rows(session)
    finally:
        session.close()

    print_report(rows)
    if args.csv_path:
        write_csv(rows, args.csv_path)
        print(f"\nCSV written to {args.csv_path}")


if __name__ == "__main__":
    sys.exit(main() or 0)
