"""Полностью очищает dev-БД от тестовых данных и загружает реальные данные
компании: 7 поставщиков, материалы из materials.csv, цены из prices_long.csv.

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
import csv
import datetime
import random
import sys
from pathlib import Path

from sqlalchemy import text

from app.core.database import SessionLocal
from app.models import Material, Price, Supplier

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "import"
MATERIALS_CSV = DATA_DIR / "materials.csv"
PRICES_CSV = DATA_DIR / "prices_long.csv"

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


def read_materials() -> list[dict]:
    with MATERIALS_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_prices() -> list[dict]:
    with PRICES_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def print_summary(db) -> None:
    print("=" * 70)
    print("СВОДКА — будет УДАЛЕНО (текущие данные dev-БД):")
    print("=" * 70)
    for table in TABLES_IN_DELETE_ORDER:
        n = db.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        print(f"  {table:30s} {n}")

    materials_rows = read_materials()
    prices_rows = read_prices()

    print()
    print("=" * 70)
    print("Будет СОЗДАНО (реальные данные компании):")
    print("=" * 70)
    print(f"  suppliers                     {len(SUPPLIER_NAMES)}  ({', '.join(SUPPLIER_NAMES)})")
    print(f"  materials                     {len(materials_rows)}  (из {MATERIALS_CSV.name})")
    print(f"  prices                        {len(prices_rows)}  (из {PRICES_CSV.name})")
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
    print("(в исходном CSV этих данных нет; NULL = 'неизвестно', выбрано вместо 0,")
    print("чтобы не путать с 'нет в наличии' / 'минимальный заказ не нужен' —")
    print("оба поля nullable в модели Price). Их тоже придётся заполнить вручную.")
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


def create_materials(db, materials_rows: list[dict]) -> dict[str, Material]:
    materials_by_description: dict[str, Material] = {}
    for row in materials_rows:
        material = Material(
            internal_sku=row["internal_sku"],
            canonical_name=row["description"],
            category=row["group"] or None,
            unit=row["unit"],
            attributes={},
        )
        db.add(material)
        materials_by_description[row["description"]] = material
    db.flush()
    return materials_by_description


def create_prices(
    db,
    prices_rows: list[dict],
    materials_by_description: dict[str, Material],
    suppliers_by_name: dict[str, Supplier],
) -> tuple[int, list[str]]:
    today = datetime.date.today()
    created = 0
    skipped: list[str] = []

    for row in prices_rows:
        description = row["description"]
        supplier_name = row["supplier"]
        material = materials_by_description.get(description)
        supplier = suppliers_by_name.get(supplier_name)

        if material is None or supplier is None:
            skipped.append(
                f"row={row.get('row')} description={description!r} supplier={supplier_name!r} "
                f"(material_found={material is not None}, supplier_found={supplier is not None})"
            )
            continue

        db.add(
            Price(
                material=material,
                supplier=supplier,
                price=row["price"],
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

    db = SessionLocal()
    try:
        print_summary(db)

        if not args.confirm:
            print("Dry-run: ничего не изменено. Перезапусти с --confirm, чтобы выполнить.")
            sys.exit(0)

        print("Выполняю очистку и импорт...")
        wipe_tables(db)

        suppliers_by_name = create_suppliers(db)
        materials_rows = read_materials()
        materials_by_description = create_materials(db, materials_rows)

        prices_rows = read_prices()
        created, skipped = create_prices(
            db, prices_rows, materials_by_description, suppliers_by_name
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
