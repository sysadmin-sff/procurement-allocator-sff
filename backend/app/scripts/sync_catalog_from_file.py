"""Synchronizes the company catalog from an updated wide-matrix xlsx price
file against an ALREADY-POPULATED database — see ADR-0035. Distinct from
import_real_data.py, which TRUNCATEs everything and is for first-load of an
empty dev DB only; this script never deletes or truncates anything.

Matching (ADR-0035 §1): exact canonical_name match after whitespace-only
normalization (strip + collapse internal whitespace) — no casefold, no
fuzzy/similarity matching. A file row whose normalized canonical_name
doesn't match any existing Material goes to unmatched_price_rows, never
silently created or skipped.

Price reconciliation (§2) for matched materials — three cases per
(material, supplier) pair, compared against the current active Price:
  (а) file has a value, differs from active -> version_price() (close old,
      open new).
  (б) file cell blank, active Price exists -> close it, no replacement.
  (в) file has a value, no active Price exists -> version_price() with no
      prior close (already version_price's own "no existing row" branch).

category_id/unit of a MATCHED material are never changed by this path (§2.1)
— any divergence between the file's Group/Quantity-derived unit and the
current DB values goes to category_or_unit_mismatches, informational only;
the price reconciliation for that same row still applies normally.

New materials (unmatched rows) are only created when their Group resolves to
an existing Category by exact name (§3) — via generate_next_sku(), never a
hand-rolled SKU formula. Unknown category -> unresolved_category_rows, the
row is not created.

Materials in the DB but absent from the file are never touched (§4) — only
listed informationally in not_in_file.

A new supplier (column header not in SUPPLIER_COLUMN_HEADERS at all) goes to
unmapped_supplier_headers and is never auto-created — requires manually
adding an entry to that dict first (§5, same discipline as
import_real_data.py already applies). A header THAT IS in
SUPPLIER_COLUMN_HEADERS but has no matching Supplier row yet is created with
DEFAULT_DELIVERY_POLICY (same placeholder as import_real_data.py) and listed
in new_suppliers with the same delivery-policy warning that script already
prints.

Dry-run (apply=False) never writes to the DB at all, including
Category.next_sku_number — new SKUs are PREDICTED by reading the current
counter without incrementing it (generate_next_sku() is not called), and the
report marks them as provisional.

--apply is one transaction for the whole run (§8): version_price() is called
with commit=False so none of its calls end the transaction prematurely, and
a single db.commit() only happens after the post-apply verification passes.
On a verification mismatch, db.rollback() undoes everything from this run.

Usage:
    python -m app.scripts.sync_catalog_from_file <path>            # dry-run
    python -m app.scripts.sync_catalog_from_file <path> --apply    # write
"""

from __future__ import annotations

import argparse
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.price import version_price
from app.core.database import SessionLocal
from app.models import Category, Material, Price, Supplier
from app.scripts.import_real_data import DEFAULT_DELIVERY_POLICY
from app.scripts.xlsx_price_matrix import MaterialRow, ParsedWorkbook, parse_price_matrix
from app.services.material_sku import generate_next_sku

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_name(name: str) -> str:
    """Whitespace-only: strip + collapse internal runs to one space. No
    casefold, no punctuation stripping — see ADR-0035 §1: more aggressive
    normalization risks merging names the file's author distinguished on
    purpose; this only removes accidental whitespace noise."""
    return _WHITESPACE_RE.sub(" ", name.strip())


# --- Report row shapes (ADR-0035 §7) ----------------------------------------


@dataclass
class PriceUpdateRow:
    material_id: uuid.UUID
    material_sku: str
    supplier_id: uuid.UUID
    supplier_name: str
    old_price: float
    new_price: float


@dataclass
class PriceClosureRow:
    material_id: uuid.UUID
    material_sku: str
    supplier_id: uuid.UUID
    supplier_name: str
    closed_price: float


@dataclass
class PriceCreationRow:
    material_id: uuid.UUID | None
    """None only for a brand-new material's price during dry-run -- the
    Material row doesn't exist yet (see _create_new_material), symmetric
    with NewMaterialRow.material_id."""
    material_sku: str
    supplier_id: uuid.UUID | None
    """None only when this row's supplier is ALSO new (not yet created) and
    this is a dry-run -- see supplier_name for the identifying string in
    that case."""
    supplier_name: str
    price: float


@dataclass
class NewMaterialRow:
    category_name: str
    predicted_sku: str
    canonical_name: str
    material_id: uuid.UUID | None = None
    """Set only when apply=True — dry-run never creates a Material, so this
    stays None and predicted_sku is provisional (see module docstring)."""


@dataclass
class UnmatchedRow:
    description: str
    category: str | None


@dataclass
class UnresolvedCategoryRow:
    description: str
    category: str | None


@dataclass
class CategoryMismatchRow:
    material_id: uuid.UUID
    material_sku: str
    current_category_name: str
    file_category_name: str | None
    current_unit: str
    file_unit: str


@dataclass
class SyncReport:
    price_updates: list[PriceUpdateRow] = field(default_factory=list)
    price_closures: list[PriceClosureRow] = field(default_factory=list)
    price_creations: list[PriceCreationRow] = field(default_factory=list)
    new_materials: list[NewMaterialRow] = field(default_factory=list)
    new_suppliers: list[str] = field(default_factory=list)
    unmatched_price_rows: list[UnmatchedRow] = field(default_factory=list)
    unresolved_category_rows: list[UnresolvedCategoryRow] = field(default_factory=list)
    category_or_unit_mismatches: list[CategoryMismatchRow] = field(default_factory=list)
    not_in_file: list[str] = field(default_factory=list)
    unmapped_supplier_headers: list[str] = field(default_factory=list)
    dry_run: bool = True
    verification_ok: bool = True
    applied_price_change_count: int = 0
    """Incremented at each point a Price is actually created/closed during
    --apply -- not derived from SQLAlchemy session introspection (db.new/
    db.dirty), since version_price(commit=False)'s own db.flush() moves new
    objects out of session.new before verification would run (confirmed
    empirically). Not part of the printed report -- an internal check value
    for _verify_and_finalize only."""


class SyncVerificationError(Exception):
    """Raised when --apply's post-apply verification finds the applied
    Price change count doesn't match the report's own counts — the whole
    transaction is rolled back before this propagates, see ADR-0035 §8."""


def _active_price(db: Session, material_id: uuid.UUID, supplier_id: uuid.UUID) -> Price | None:
    return (
        db.query(Price)
        .filter(
            Price.material_id == material_id,
            Price.supplier_id == supplier_id,
            Price.valid_to.is_(None),
        )
        .first()
    )


def _resolve_suppliers(
    db: Session, workbook: ParsedWorkbook, apply: bool, report: SyncReport
) -> dict[str, Supplier]:
    """Maps supplier display name (SUPPLIER_COLUMN_HEADERS values found in
    the file's header row) -> Supplier row, creating any recognized-but-
    missing supplier with the same placeholder delivery_policy
    import_real_data.py uses (§5). unmapped_supplier_headers is already
    populated by parse_price_matrix() itself; copied through unchanged."""
    report.unmapped_supplier_headers = list(workbook.unmapped_supplier_headers)

    file_supplier_names = set(workbook.recognized_supplier_columns)
    existing = {s.name: s for s in db.scalars(select(Supplier)).all()}

    resolved: dict[str, Supplier] = {}
    for name in sorted(file_supplier_names):
        supplier = existing.get(name)
        if supplier is None:
            report.new_suppliers.append(name)
            if apply:
                supplier = Supplier(
                    name=name, currency="USD", delivery_policy=dict(DEFAULT_DELIVERY_POLICY)
                )
                db.add(supplier)
                db.flush()
                existing[name] = supplier
            else:
                continue
        resolved[name] = supplier
    return resolved


def _reconcile_prices(
    db: Session,
    material_id: uuid.UUID,
    material_sku: str,
    prices_by_supplier: dict[str, float | None],
    suppliers: dict[str, Supplier],
    apply: bool,
    report: SyncReport,
) -> None:
    """One (material, supplier) pair at a time — the three cases of
    ADR-0035 §2. A supplier column with no header mapping at all
    (unmapped_supplier_headers) is skipped entirely -- no way to know who
    the supplier even is. A RECOGNIZED but not-yet-created supplier during
    dry-run has no id to query an active Price against, but a blank file
    cell for it is meaningless (case б requires an EXISTING active Price,
    impossible for a supplier that doesn't exist) -- so any non-blank cell
    is unconditionally case (в), reported with supplier_id=None."""
    for supplier_name, file_price in prices_by_supplier.items():
        supplier = suppliers.get(supplier_name)
        if supplier is None:
            if file_price is not None:
                report.price_creations.append(
                    PriceCreationRow(
                        material_id=material_id,
                        material_sku=material_sku,
                        supplier_id=None,
                        supplier_name=supplier_name,
                        price=file_price,
                    )
                )
            continue

        active = _active_price(db, material_id, supplier.id)

        if file_price is not None and active is not None and float(active.price) != file_price:
            report.price_updates.append(
                PriceUpdateRow(
                    material_id=material_id,
                    material_sku=material_sku,
                    supplier_id=supplier.id,
                    supplier_name=supplier_name,
                    old_price=float(active.price),
                    new_price=file_price,
                )
            )
            if apply:
                version_price(
                    db,
                    material_id=material_id,
                    supplier_id=supplier.id,
                    price=file_price,
                    commit=False,
                )
                report.applied_price_change_count += 1
        elif file_price is None and active is not None:
            report.price_closures.append(
                PriceClosureRow(
                    material_id=material_id,
                    material_sku=material_sku,
                    supplier_id=supplier.id,
                    supplier_name=supplier_name,
                    closed_price=float(active.price),
                )
            )
            if apply:
                import datetime

                active.valid_to = datetime.date.today()
                report.applied_price_change_count += 1
        elif file_price is not None and active is None:
            report.price_creations.append(
                PriceCreationRow(
                    material_id=material_id,
                    material_sku=material_sku,
                    supplier_id=supplier.id,
                    supplier_name=supplier_name,
                    price=file_price,
                )
            )
            if apply:
                version_price(
                    db,
                    material_id=material_id,
                    supplier_id=supplier.id,
                    price=file_price,
                    commit=False,
                )
                report.applied_price_change_count += 1
        # file_price is None and active is None: nothing in the file, nothing
        # active -- no case applies, no report row, no action.


def run_sync(db: Session, path: Path, apply: bool) -> SyncReport:
    report = SyncReport(dry_run=not apply)
    workbook = parse_price_matrix(path)

    suppliers = _resolve_suppliers(db, workbook, apply, report)

    # Dry-run SKU prediction: purely in-memory, per-category counter that
    # simulates what generate_next_sku()'s atomic UPDATE would do during
    # --apply, one increment per new material predicted in THIS pass --
    # without it, every new material of the same category would read the
    # same unchanged Category.next_sku_number and predict the identical SKU
    # (real bug found in production use: 4 new Profil materials in one file
    # all predicted "PROF-069"). Never written to the DB -- apply=True
    # doesn't use this dict at all, it calls the real generate_next_sku().
    next_sku_number_by_category_id: dict[uuid.UUID, int] = {}

    # Every recognized supplier column starts at None (blank in the file) so
    # case (б) -- blank cell + existing active Price -- can be detected even
    # for a column where this particular row's cell never produced a
    # PriceCell. Cells that did parse then override their supplier's None.
    prices_by_description: dict[str, dict[str, float | None]] = {
        row.description: dict.fromkeys(workbook.recognized_supplier_columns)
        for row in workbook.materials
    }
    for cell in workbook.prices:
        prices_by_description[cell.description][cell.supplier_name] = cell.price

    existing_materials = db.scalars(select(Material)).all()
    by_normalized_name: dict[str, Material] = {
        _normalize_name(m.canonical_name): m for m in existing_materials
    }
    matched_material_ids: set[uuid.UUID] = set()

    categories_by_name = {c.name: c for c in db.scalars(select(Category)).all()}

    for row in workbook.materials:
        normalized = _normalize_name(row.description)
        material = by_normalized_name.get(normalized)
        file_prices = prices_by_description.get(row.description, {})

        if material is not None:
            matched_material_ids.add(material.id)
            _check_category_and_unit_mismatch(material, row, categories_by_name, report)
            _reconcile_prices(
                db, material.id, material.internal_sku, file_prices, suppliers, apply, report
            )
            continue

        # ADR-0035 §1: unmatched_price_rows is the full, unconditional audit
        # trail of every row that failed exact canonical_name matching --
        # populated here regardless of what §3 does with the row next (auto-
        # create if the category resolves, or unresolved_category_rows if it
        # doesn't). The two lists are not mutually exclusive alternatives.
        report.unmatched_price_rows.append(
            UnmatchedRow(description=row.description, category=row.category)
        )

        category = categories_by_name.get(row.category) if row.category else None
        if category is None:
            report.unresolved_category_rows.append(
                UnresolvedCategoryRow(description=row.description, category=row.category)
            )
            continue

        new_material_row = _create_new_material(
            db,
            row,
            category,
            file_prices,
            suppliers,
            apply,
            report,
            next_sku_number_by_category_id,
        )
        report.new_materials.append(new_material_row)

    for material in existing_materials:
        if material.id not in matched_material_ids:
            report.not_in_file.append(material.internal_sku)

    if apply:
        _verify_and_finalize(db, report)

    return report


def _check_category_and_unit_mismatch(
    material: Material,
    row: MaterialRow,
    categories_by_name: dict[str, Category],
    report: SyncReport,
) -> None:
    """ADR-0035 §2.1: category_id/unit of a matched Material are NEVER
    changed by this script. A divergence is only ever reported, never
    applied — informational, doesn't block the price reconciliation for
    the same row."""
    file_category = categories_by_name.get(row.category) if row.category else None
    category_mismatch = file_category is not None and file_category.id != material.category_id
    unit_mismatch = row.unit != material.unit

    if category_mismatch or unit_mismatch:
        report.category_or_unit_mismatches.append(
            CategoryMismatchRow(
                material_id=material.id,
                material_sku=material.internal_sku,
                current_category_name=material.category.name,
                file_category_name=row.category,
                current_unit=material.unit,
                file_unit=row.unit,
            )
        )


def _create_new_material(
    db: Session,
    row: MaterialRow,
    category: Category,
    file_prices: dict[str, float],
    suppliers: dict[str, Supplier],
    apply: bool,
    report: SyncReport,
    next_sku_number_by_category_id: dict[uuid.UUID, int],
) -> NewMaterialRow:
    if apply:
        sku = generate_next_sku(db, category.id)
        material = Material(
            internal_sku=sku,
            canonical_name=row.description,
            category_id=category.id,
            unit=row.unit,
            attributes={},
        )
        db.add(material)
        db.flush()
        _reconcile_prices(db, material.id, sku, file_prices, suppliers, apply, report)
        return NewMaterialRow(
            category_name=category.name,
            predicted_sku=sku,
            canonical_name=row.description,
            material_id=material.id,
        )

    # Local, in-memory increment per category -- mirrors generate_next_sku()'s
    # atomic UPDATE without touching the DB (see run_sync's comment on
    # next_sku_number_by_category_id). First new material of this category in
    # this pass seeds from the real Category.next_sku_number; every
    # subsequent one in the same pass reads the already-incremented value.
    next_number = next_sku_number_by_category_id.setdefault(
        category.id, category.next_sku_number
    )
    predicted_sku = f"{category.sku_prefix}-{next_number:03d}"
    next_sku_number_by_category_id[category.id] = next_number + 1
    # No real material_id yet in dry-run -- every supplier price for a
    # brand-new material is unconditionally case (в) (no existing Price row
    # could exist for a Material that doesn't exist yet), so report it
    # directly rather than routing through _reconcile_prices/_active_price,
    # which need a real material_id to query against.
    for supplier_name, file_price in file_prices.items():
        if file_price is None:
            continue
        supplier = suppliers.get(supplier_name)
        report.price_creations.append(
            PriceCreationRow(
                material_id=None,
                material_sku=predicted_sku,
                supplier_id=supplier.id if supplier is not None else None,
                supplier_name=supplier_name,
                price=file_price,
            )
        )
    return NewMaterialRow(
        category_name=category.name,
        predicted_sku=predicted_sku,
        canonical_name=row.description,
    )


def _verify_and_finalize(db: Session, report: SyncReport) -> None:
    """ADR-0035 §8: sum of reported price_updates+price_closures+
    price_creations must equal the number of Price changes actually applied
    during this run. Compared against an explicit counter
    (applied_price_change_count) incremented at each real apply point,
    rather than introspecting db.new/db.dirty -- version_price(commit=False)
    calls db.flush() internally, which moves newly-added objects out of
    session.new into the identity map, so db.new is empty by the time this
    function runs (confirmed empirically, not an assumption)."""
    expected = len(report.price_updates) + len(report.price_closures) + len(report.price_creations)
    actual = report.applied_price_change_count

    if actual != expected:
        report.verification_ok = False
        db.rollback()
        raise SyncVerificationError(
            f"Verification failed: report claims {expected} price changes "
            f"(updates={len(report.price_updates)}, closures={len(report.price_closures)}, "
            f"creations={len(report.price_creations)}), but only {actual} were actually "
            f"applied. Rolled back the entire transaction."
        )

    db.commit()


def print_report(report: SyncReport) -> None:
    print("=" * 70)
    print("СИНХРОНИЗАЦИЯ КАТАЛОГА" + (" (dry-run)" if report.dry_run else " (--apply)"))
    print("=" * 70)

    print(f"\nОбновления цен (price_updates): {len(report.price_updates)}")
    for row in report.price_updates:
        print(
            f"  {row.material_sku} / {row.supplier_name}: "
            f"{row.old_price} -> {row.new_price}"
        )

    print(f"\nЗакрытия цен без замены (price_closures): {len(report.price_closures)}")
    for row in report.price_closures:
        print(f"  {row.material_sku} / {row.supplier_name}: закрыта цена {row.closed_price}")

    print(f"\nНовые цены (price_creations): {len(report.price_creations)}")
    for row in report.price_creations:
        print(f"  {row.material_sku} / {row.supplier_name}: новая цена {row.price}")

    print(f"\nНовые материалы (new_materials): {len(report.new_materials)}")
    for row in report.new_materials:
        provisional = "" if not report.dry_run else " (предварительно, может измениться к --apply)"
        print(f"  {row.predicted_sku}{provisional}: {row.canonical_name!r} [{row.category_name}]")

    print(f"\nНовые поставщики (new_suppliers): {len(report.new_suppliers)}")
    for name in report.new_suppliers:
        print(f"  {name}")
    if report.new_suppliers:
        print("  ВАЖНО: delivery_policy у новых поставщиков создаётся с")
        print("    free_shipping_threshold = null (порог не настроен, ADR-0003)")
        print("    flat_fee = 0.0 (заглушка — единственное валидное значение схемы,")
        print("                    null не поддерживается для этого поля)")
        print("  Пока пользователь не заполнит реальные flat_fee вручную через /suppliers,")
        print("  все allocation-расчёты будут показывать 'доставка бесплатно' для этих")
        print("  поставщиков — это ОЖИДАЕМОЕ поведение при flat_fee=0.0, не баг.")

    print(
        f"\nНесопоставленные строки файла (unmatched_price_rows): "
        f"{len(report.unmatched_price_rows)}"
    )
    for row in report.unmatched_price_rows:
        print(f"  {row.description!r} [{row.category}]")

    print(
        f"\nСтроки с неизвестной категорией (unresolved_category_rows): "
        f"{len(report.unresolved_category_rows)}"
    )
    for row in report.unresolved_category_rows:
        print(f"  {row.description!r}: категория {row.category!r} не найдена")

    print(
        f"\nРасхождения категории/unit у совпавших материалов "
        f"(category_or_unit_mismatches): {len(report.category_or_unit_mismatches)}"
    )
    for row in report.category_or_unit_mismatches:
        print(
            f"  {row.material_sku}: категория БД={row.current_category_name!r} vs "
            f"файл={row.file_category_name!r}, unit БД={row.current_unit!r} vs "
            f"файл={row.file_unit!r} — не изменено"
        )

    print(f"\nМатериалы БД, отсутствующие в файле (not_in_file): {len(report.not_in_file)}")
    for sku in report.not_in_file:
        print(f"  {sku}")

    print(
        f"\nНераспознанные заголовки колонок-поставщиков "
        f"(unmapped_supplier_headers): {len(report.unmapped_supplier_headers)}"
    )
    for header in report.unmapped_supplier_headers:
        print(f"  {header!r} — добавь запись в SUPPLIER_COLUMN_HEADERS вручную")

    print()
    print(
        "Проверь вручную перед --apply: price_closures не аномально велико, "
        "unresolved_category_rows и unmatched_price_rows пусты или разобраны вручную, "
        "new_suppliers ожидаем."
    )
    if report.dry_run:
        print("Dry-run: ничего не изменено. Перезапусти с --apply, чтобы записать.")
    elif not report.verification_ok:
        print("ОШИБКА: верификация после --apply не прошла — транзакция откачена.")
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
        report = run_sync(db, args.path, apply=args.apply)
        print_report(report)
    finally:
        db.close()


if __name__ == "__main__":
    main()
