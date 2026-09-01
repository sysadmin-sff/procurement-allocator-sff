"""Полностью очищает dev-БД от тестовых данных и загружает реальные данные
компании: 7 поставщиков, материалы и цены из одного xlsx-файла
(матрица "материал × поставщик", формат обновлённого прайса от компании —
см. app/scripts/xlsx_price_matrix.py за разбором структуры и его же
доктстринг про историю формата: раньше это были два CSV,
materials.csv/prices_long.csv, тот путь оставлен только для справки).

Отдельный скрипт от seed.py — seed.py остаётся для будущих dev-окружений
с нуля (синтетические данные), этот скрипт — одноразовая замена реальных
данных в уже существующей dev-БД.

Использование:
    python -m app.scripts.import_real_data            # dry-run: только сводка
    python -m app.scripts.import_real_data --confirm   # реально выполнить очистку + импорт

Без --confirm скрипт только печатает сводку (что будет удалено/создано)
и останавливается — ничего не меняет в БД.
"""

import argparse
import datetime
import random
import sys
from pathlib import Path

from sqlalchemy import text

from app.core.database import SessionLocal
from app.models import Material, Price, Supplier
from app.scripts.xlsx_price_matrix import FALLBACK_UNIT, ParsedWorkbook, parse_price_matrix

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "import"
PRICE_MATRIX_XLSX = DATA_DIR / "materials_price_matrix.xlsx"

SUPPLIER_NAMES = [
    "EMS",
    "Lancing",
    "JM Fasteners",
    "Aluminum Distributors Int LLC",
    "Florida Sales & Marketing",
    "American Metals Supply",
    "Classic Metals",
]

# Соответствует дефолту DeliveryPolicy() в app/api/schemas/supplier.py:
# free_shipping_threshold=None ("порог не настроен", ADR-0003), flat_fee=0.0
# (null не поддерживается схемой, 0.0 — единственное валидное "не настроено").
DEFAULT_DELIVERY_POLICY = {
    "flat_fee": 0.0,
    "free_shipping_threshold": None,
    "per_order_min_amount": 0.0,
    "lead_time_days": 0,
}

# Таблицы в порядке удаления: дети перед родителями (FK-safe).
TABLES_IN_DELETE_ORDER = [
    "allocation_lines",
    "allocation_runs",
    "project_items",
    "projects",
    "order_items",
    "orders",
    "prices",
    "supplier_material_aliases",
    "price_list_entries",
    "price_list_imports",
    "materials",
    "suppliers",
]


def read_workbook() -> ParsedWorkbook:
    return parse_price_matrix(PRICE_MATRIX_XLSX)


def print_summary(db, workbook: ParsedWorkbook) -> None:
    print("=" * 70)
    print("СВОДКА — будет УДАЛЕНО (текущие данные dev-БД):")
    print("=" * 70)
    for table in TABLES_IN_DELETE_ORDER:
        n = db.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        print(f"  {table:30s} {n}")

    print()
    print("=" * 70)
    print("Будет СОЗДАНО (реальные данные компании, из"
          f" {PRICE_MATRIX_XLSX.name}):")
    print("=" * 70)
    print(f"  suppliers                     {len(SUPPLIER_NAMES)}  ({', '.join(SUPPLIER_NAMES)})")
    print(f"  materials                     {len(workbook.materials)}")
    print(f"  prices                        {len(workbook.prices)}")
    print()
    print("ВАЖНО: delivery_policy у новых поставщиков создаётся с")
    print("  free_shipping_threshold = null (порог не настроен, ADR-0003)")
    print("  flat_fee = 0.0 (заглушка — единственное валидное значение схемы,")
    print("                  null не поддерживается для этого поля)")
    print("Пока пользователь не заполнит реальные flat_fee вручную через /suppliers,")
    print("все allocation-расчёты будут показывать 'доставка бесплатно' для всех")
    print("поставщиков — это ОЖИДАЕМОЕ поведение при flat_fee=0.0, не баг.")
    print()
    print("availability и min_order_qty на новых Price-записях будут NULL")
    print("(в исходном файле этих данных нет; NULL = 'неизвестно', выбрано вместо 0,")
    print("чтобы не путать с 'нет в наличии' / 'минимальный заказ не нужен' —")
    print("оба поля nullable в модели Price). Их тоже придётся заполнить вручную.")
    print()

    print("=" * 70)
    print("Замечания парсинга исходного xlsx (проверить перед --confirm):")
    print("=" * 70)
    print(f"  Строк-разделителей секций пропущено: {workbook.divider_rows_skipped}")
    if workbook.rows_with_fallback_unit:
        print(
            f"  Материалов без Quantity в файле — unit проставлен "
            f"'{FALLBACK_UNIT}' по умолчанию, требует ручной проверки: "
            f"{len(workbook.rows_with_fallback_unit)}"
        )
        for desc in workbook.rows_with_fallback_unit:
            print(f"    - {desc}")
    if workbook.unparseable_price_cells:
        print(f"  Нечитаемых значений цены (пропущены): {len(workbook.unparseable_price_cells)}")
        for row_number, supplier_name, raw in workbook.unparseable_price_cells:
            print(f"    - строка {row_number}, {supplier_name}: {raw!r}")
    if workbook.unmapped_supplier_headers:
        print(
            "  ВНИМАНИЕ: заголовки колонок в файле без сопоставления поставщику "
            "(цены из этих колонок НЕ будут импортированы):"
        )
        for header in workbook.unmapped_supplier_headers:
            print(f"    - {header!r}")
    print()


def wipe_tables(db) -> None:
    for table in TABLES_IN_DELETE_ORDER:
        db.execute(text(f"TRUNCATE TABLE {table} CASCADE"))


def create_suppliers(db) -> dict[str, Supplier]:
    suppliers_by_name: dict[str, Supplier] = {}
    for name in SUPPLIER_NAMES:
        supplier = Supplier(
            name=name,
            contacts=None,
            currency="USD",
            delivery_policy=dict(DEFAULT_DELIVERY_POLICY),
        )
        db.add(supplier)
        suppliers_by_name[name] = supplier
    db.flush()
    return suppliers_by_name


def create_materials(db, materials_rows: list) -> dict[str, Material]:
    materials_by_description: dict[str, Material] = {}
    for row in materials_rows:
        material = Material(
            internal_sku=row.internal_sku,
            canonical_name=row.description,
            category=row.category,
            unit=row.unit,
            attributes={},
        )
        db.add(material)
        materials_by_description[row.description] = material
    db.flush()
    return materials_by_description


def create_prices(
    db,
    prices_rows: list,
    materials_by_description: dict[str, Material],
    suppliers_by_name: dict[str, Supplier],
) -> tuple[int, list[str]]:
    today = datetime.date.today()
    created = 0
    skipped: list[str] = []

    for row in prices_rows:
        material = materials_by_description.get(row.description)
        supplier = suppliers_by_name.get(row.supplier_name)

        if material is None or supplier is None:
            skipped.append(
                f"description={row.description!r} supplier={row.supplier_name!r} "
                f"(material_found={material is not None}, supplier_found={supplier is not None})"
            )
            continue

        db.add(
            Price(
                material=material,
                supplier=supplier,
                price=row.price,
                currency="USD",
                availability=None,
                min_order_qty=None,
                valid_from=today,
                valid_to=None,
            )
        )
        created += 1

    return created, skipped


def verify(db) -> None:
    print()
    print("=" * 70)
    print("ВЕРИФИКАЦИЯ — итоговые counts:")
    print("=" * 70)
    for table in TABLES_IN_DELETE_ORDER:
        n = db.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        print(f"  {table:30s} {n}")

    print()
    print("=" * 70)
    print("Выборка: 5 случайных материалов с ценами у разных поставщиков")
    print("=" * 70)
    materials = db.query(Material).all()
    sample = random.sample(materials, min(5, len(materials)))
    for material in sample:
        print(
            f"\n[{material.internal_sku}] {material.canonical_name} "
            f"({material.unit}, {material.category})"
        )
        prices = (
            db.query(Price)
            .filter(Price.material_id == material.id)
            .join(Supplier)
            .order_by(Supplier.name)
            .all()
        )
        if not prices:
            print("    (нет цен)")
        for p in prices:
            print(f"    {p.supplier.name:35s} ${p.price}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Реально выполнить очистку и импорт (без этого флага — только сводка, dry-run).",
    )
    args = parser.parse_args()

    workbook = read_workbook()

    db = SessionLocal()
    try:
        print_summary(db, workbook)

        if not args.confirm:
            print("Dry-run: ничего не изменено. Перезапусти с --confirm, чтобы выполнить.")
            sys.exit(0)

        print("Выполняю очистку и импорт...")
        wipe_tables(db)

        suppliers_by_name = create_suppliers(db)
        materials_by_description = create_materials(db, workbook.materials)

        created, skipped = create_prices(
            db, workbook.prices, materials_by_description, suppliers_by_name
        )

        db.commit()

        print(f"\nСоздано: {len(suppliers_by_name)} поставщиков, "
              f"{len(materials_by_description)} материалов, {created} цен.")
        if skipped:
            print(f"\nПРОПУЩЕНО {len(skipped)} строк цен (не найден материал/поставщик):")
            for s in skipped:
                print(f"  - {s}")

        verify(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
