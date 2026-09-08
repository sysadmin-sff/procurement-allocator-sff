"""Одноразовый бэкафилл color_options/color_fragment для существующего
каталога Material — см. ADR-0031 п.1. Того же семейства, что
backfill_material_embeddings.py: dry-run по умолчанию, --apply для записи.

Идемпотентен: повторный запуск трогает только строки, у которых
color_options IS NULL (в т.ч. уже заполненные импортом новых материалов,
не переобрабатываются).

Использование:
    python -m app.scripts.backfill_color_options            # dry-run
    python -m app.scripts.backfill_color_options --apply    # запись
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Material
from app.services.material_naming import parse_color


@dataclass
class BackfillRow:
    internal_sku: str
    canonical_name: str
    color_options: list[str]
    color_fragment: str
    pattern: str


@dataclass
class BackfillReport:
    recognized: list[BackfillRow] = field(default_factory=list)
    unrecognized: list[str] = field(default_factory=list)
    """canonical_name of materials that contain something color-shaped but
    were not recognized confidently — ADR-0031 п.1 step 2: must be listed
    explicitly, never silently skipped. Empty for the real catalog as of
    ADR-0031 Step 0, but the script must still report it if it ever
    happens."""


def run_backfill(db: Session, apply: bool) -> BackfillReport:
    materials = db.scalars(select(Material).where(Material.color_options.is_(None))).all()

    report = BackfillReport()
    for material in materials:
        result = parse_color(material.canonical_name)
        if result is None:
            continue

        report.recognized.append(
            BackfillRow(
                internal_sku=material.internal_sku,
                canonical_name=material.canonical_name,
                color_options=result.color_options,
                color_fragment=result.color_fragment,
                pattern=result.pattern,
            )
        )
        if apply:
            material.color_options = result.color_options
            material.color_fragment = result.color_fragment

    if apply:
        db.commit()

    return report


def print_report(report: BackfillReport, apply: bool) -> None:
    print("=" * 70)
    print(f"Материалов распознано: {len(report.recognized)}")
    print("=" * 70)
    for row in report.recognized:
        print(
            f"  [{row.internal_sku}] {row.canonical_name!r}\n"
            f"      -> color_options={row.color_options} "
            f"color_fragment={row.color_fragment!r} (паттерн: {row.pattern})"
        )
    print()
    if report.unrecognized:
        print("=" * 70)
        print(f"НЕ смог распознать уверенно ({len(report.unrecognized)}):")
        print("=" * 70)
        for name in report.unrecognized:
            print(f"  - {name!r}")
        print()
    if apply:
        print(f"Записано в БД: {len(report.recognized)} материалов.")
    else:
        print("Dry-run: ничего не изменено. Перезапусти с --apply, чтобы записать.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Реально записать color_options/color_fragment (без флага — dry-run).",
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
