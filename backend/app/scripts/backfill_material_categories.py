"""One-time backfill: creates Category rows from the existing distinct
Material.category string values and links Material.category_id — see
ADR-0034 п.2. Same dry-run/--apply shape as backfill_color_options.py.

Critical difference from backfill_color_options.py: this backfill sets
requires_single_supplier, which directly drives the ILP solver's strict-
category grouping (ADR-0028) for the whole catalog from the moment --apply
runs. The dry-run report must be reviewed against the known set
{Doors, Gutter, Profil, Mesh, Roof panels} -> True before running --apply.

Usage:
    python -m app.scripts.backfill_material_categories            # dry-run
    python -m app.scripts.backfill_material_categories --apply    # write
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Category, Material
from app.scripts.xlsx_price_matrix import CATEGORY_SKU_PREFIX

STRICT_CATEGORY_NAMES = {"Doors", "Gutter", "Profil", "Mesh", "Roof panels"}
"""ADR-0028's five visually-facing categories -- requires_single_supplier=True
after this backfill. Lives here, not in solver.py: after ADR-0034, solver.py
no longer knows category names at all, only category_id + a bool it reads
from the DB. This constant exists solely to seed that DB value once."""

_SKU_SUFFIX_RE = re.compile(r"-(\d+)$")


class UnknownCategoryError(Exception):
    """A Material.category value has no entry in CATEGORY_SKU_PREFIX -- must
    not silently fall back to MISC/an arbitrary prefix, see ADR-0034 п.2."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(
            f"Category {category!r} found in materials but missing from "
            f"CATEGORY_SKU_PREFIX -- refusing to guess a sku_prefix"
        )


@dataclass
class BackfillCategoryRow:
    name: str
    sku_prefix: str
    requires_single_supplier: bool
    material_count: int
    next_sku_number: int


@dataclass
class BackfillReport:
    category_rows: list[BackfillCategoryRow] = field(default_factory=list)
    unknown_categories: list[str] = field(default_factory=list)
    null_category_id_before: int = 0
    null_category_id_after: int = 0
    verification_ok: bool = True


def _max_sku_suffix(materials: list[Material]) -> int:
    best = 0
    for material in materials:
        match = _SKU_SUFFIX_RE.search(material.internal_sku)
        if match:
            best = max(best, int(match.group(1)))
    return best


def _link_materials_to_categories(db: Session, category_by_name: dict[str, Category]) -> None:
    materials = db.scalars(select(Material).where(Material.category.is_not(None))).all()
    for material in materials:
        material.category_id = category_by_name[material.category].id


def run_backfill(db: Session, apply: bool) -> BackfillReport:
    report = BackfillReport()

    report.null_category_id_before = (
        db.query(Material).filter(Material.category.is_(None)).count()
    )

    distinct_categories = [
        row[0]
        for row in db.execute(
            select(Material.category).distinct().where(Material.category.is_not(None))
        ).all()
    ]

    unknown = [c for c in distinct_categories if c not in CATEGORY_SKU_PREFIX]
    if unknown:
        report.unknown_categories = unknown
        if apply:
            raise UnknownCategoryError(unknown[0])
        return report

    existing_by_name = {c.name: c for c in db.scalars(select(Category)).all()}

    category_by_name: dict[str, Category] = {}
    for name in distinct_categories:
        materials = db.scalars(select(Material).where(Material.category == name)).all()
        sku_prefix = CATEGORY_SKU_PREFIX[name]
        next_sku_number = _max_sku_suffix(materials) + 1
        requires_single_supplier = name in STRICT_CATEGORY_NAMES

        existing = existing_by_name.get(name)
        report.category_rows.append(
            BackfillCategoryRow(
                name=name,
                sku_prefix=existing.sku_prefix if existing else sku_prefix,
                requires_single_supplier=(
                    existing.requires_single_supplier if existing else requires_single_supplier
                ),
                material_count=len(materials),
                next_sku_number=existing.next_sku_number if existing else next_sku_number,
            )
        )

        if apply:
            if existing is not None:
                # Idempotent: a prior run already created this Category (its
                # own commit is why this Material scan still finds the name --
                # Material.category isn't dropped until the follow-up
                # migration). Re-link only, never insert a duplicate row.
                category_by_name[name] = existing
                continue

            category = Category(
                name=name,
                sku_prefix=sku_prefix,
                requires_single_supplier=requires_single_supplier,
                next_sku_number=next_sku_number,
            )
            db.add(category)
            db.flush()
            category_by_name[name] = category

    if apply:
        _link_materials_to_categories(db, category_by_name)
        db.flush()

        report.null_category_id_after = (
            db.query(Material).filter(Material.category_id.is_(None)).count()
        )
        report.verification_ok = (
            report.null_category_id_after == report.null_category_id_before
        )

        if not report.verification_ok:
            db.rollback()
        else:
            db.commit()
    else:
        report.null_category_id_after = report.null_category_id_before

    return report


def print_report(report: BackfillReport, apply: bool) -> None:
    print("=" * 70)
    print(f"Категорий найдено: {len(report.category_rows)}")
    print("=" * 70)
    for row in report.category_rows:
        print(
            f"  {row.name!r} -> sku_prefix={row.sku_prefix!r}, "
            f"requires_single_supplier={row.requires_single_supplier}, "
            f"материалов={row.material_count}, next_sku_number={row.next_sku_number}"
        )
    print()

    if report.unknown_categories:
        print("=" * 70)
        print(f"ОШИБКА: категории вне CATEGORY_SKU_PREFIX: {report.unknown_categories}")
        print("=" * 70)
        return

    print(
        "Проверь вручную: {Doors, Gutter, Profil, Mesh, Roof panels} -> True, "
        "остальные -> False, и что нет неожиданной 9-й категории."
    )
    print(
        f"category_id IS NULL до операции: {report.null_category_id_before}, "
        f"после: {report.null_category_id_after}"
    )
    if not report.verification_ok:
        print(
            "ОШИБКА: несоответствие количества NULL -- откат"
            + (" выполнен" if apply else " (dry-run, ничего не менялось)")
        )
    elif apply:
        print(f"Записано в БД: {len(report.category_rows)} категорий.")
    else:
        print("Dry-run: ничего не изменено. Перезапусти с --apply, чтобы записать.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Реально записать Category и Material.category_id (без флага — dry-run).",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        report = run_backfill(db, apply=args.apply)
        print_report(report, apply=args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    main()
