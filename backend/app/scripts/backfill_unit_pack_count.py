"""One-off backfill for Material.unit values corrupted by the pre-ADR-0036
`_clean_unit()` bug: units stored with an uninformative leading pack count
of 1 ("1 sq ft", "1 pcs" instead of "sq ft", "pcs") — see ADR-0036.

sync_catalog_from_file.py deliberately never overwrites an existing
Material's unit/category_id (ADR-0035 §2.1) — that stays true here too.
This is a separate, explicit script precisely because fixing already-stored
data needs a human decision per ADR-0035's own reasoning, not a silent
migration bundled into the regular sync path.

Detection is DB-only (Material.unit itself, not a re-read of the source
file): any material whose current unit matches "1 <something>" is a
candidate — that shape can only come from the old _clean_unit passing a
pack-of-1 Quantity cell straight through, since nothing else in this
codebase writes Material.unit from a template that starts with a literal
count. The source xlsx is used only to CONFIRM each candidate (the file's
row for that material, re-parsed with the fixed _clean_unit, must resolve
to the same cleaned unit) before writing anything — a candidate whose file
row doesn't confirm is left alone and reported separately for manual look,
rather than guessed at.

A pack count other than 1 (e.g. "5 box") is NEVER a candidate — same
reasoning as _clean_unit/ADR-0036: that's real pack-size information, not
a cleanup target.

Usage:
    python -m app.scripts.backfill_unit_pack_count <path-to-xlsx>              # dry-run
    python -m app.scripts.backfill_unit_pack_count <path-to-xlsx> --apply
"""

from __future__ import annotations

import argparse
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Material
from app.scripts.sync_catalog_from_file import _normalize_name
from app.scripts.xlsx_price_matrix import parse_price_matrix

_PACK_OF_ONE_RE = re.compile(r"^1\s+(.+)$")


@dataclass
class UnitBackfillRow:
    material_id: uuid.UUID
    material_sku: str
    old_unit: str
    new_unit: str


@dataclass
class UnitBackfillReport:
    corrected: list[UnitBackfillRow] = field(default_factory=list)
    unconfirmed: list[str] = field(default_factory=list)
    """SKUs shaped like "1 <unit>" in the DB whose file row (by matched
    canonical_name) doesn't confirm the same cleaned unit, or has no
    matching row at all — left untouched, flagged for manual review."""
    dry_run: bool = True


def plan_unit_backfill(db: Session, path: Path) -> UnitBackfillReport:
    workbook = parse_price_matrix(path)
    cleaned_unit_by_name = {
        _normalize_name(row.description): row.unit for row in workbook.materials
    }

    report = UnitBackfillReport()
    candidates = db.execute(select(Material)).scalars().all()
    for material in candidates:
        match = _PACK_OF_ONE_RE.match(material.unit)
        if match is None:
            continue  # not shaped like "1 <unit>" — not this bug

        expected_cleaned_unit = cleaned_unit_by_name.get(_normalize_name(material.canonical_name))
        if expected_cleaned_unit != match.group(1):
            report.unconfirmed.append(material.internal_sku)
            continue

        report.corrected.append(
            UnitBackfillRow(
                material_id=material.id,
                material_sku=material.internal_sku,
                old_unit=material.unit,
                new_unit=expected_cleaned_unit,
            )
        )

    return report


def apply_unit_backfill(db: Session, report: UnitBackfillReport) -> None:
    by_id = {m.id: m for m in db.execute(select(Material)).scalars()}
    for row in report.corrected:
        by_id[row.material_id].unit = row.new_unit
    db.commit()


def print_report(report: UnitBackfillReport) -> None:
    print("=" * 70)
    print("BACKFILL Material.unit (ADR-0036)" + (" (dry-run)" if report.dry_run else " (--apply)"))
    print("=" * 70)

    print(f"\nМатериалы к исправлению: {len(report.corrected)}")
    for row in report.corrected:
        print(f"  {row.material_sku}: {row.old_unit!r} -> {row.new_unit!r}")

    print(f"\nНе подтверждено файлом, требуют ручной проверки: {len(report.unconfirmed)}")
    for sku in report.unconfirmed:
        print(f"  {sku}")

    print()
    if report.dry_run:
        print("Dry-run: ничего не изменено. Перезапусти с --apply, чтобы записать.")
    else:
        print("Записано в БД.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Реально записать изменения (без флага — dry-run).",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        report = plan_unit_backfill(db, args.path)
        report.dry_run = not args.apply
        if args.apply:
            apply_unit_backfill(db, report)
        print_report(report)
    finally:
        db.close()


if __name__ == "__main__":
    main()
