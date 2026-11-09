"""Removes the rows that test runs left in the local dev database.

    python -m app.scripts.cleanup_dev_test_data           # read-only list
    python -m app.scripts.cleanup_dev_test_data --apply   # one transaction

Refuses to run on anything but the local `procurement-allocator` database.
Anything unexpected about the rows stops the script before it deletes.
"""

import argparse
import sys
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.database import engine

DEV_DATABASE_NAME = "procurement-allocator"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

TEST_USER_EMAILS = [
    "admin-material16@screen-factory-florida.com",
    "admin-material18@screen-factory-florida.com",
    "admin-supplier12@screen-factory-florida.com",
    "admin-template14@screen-factory-florida.com",
]
TEST_CATEGORY_PATTERN = "Test Category %"
TEST_SUPPLIER_NAMES = ["Ref Supplier", "Referenced Supplier"]

PROTECTED_EMAIL = "sysadmin@screen-factory-florida.com"
PROTECTED_CATEGORIES = [
    "Caulk",
    "Connectors",
    "Doors",
    "Gutter",
    "Mesh",
    "Profil",
    "Roof panels",
    "Screws",
]
PROTECTED_ORDER_ITEM_ID = "3473b863-6de1-45cb-a27e-76436a6d3a1c"

# Children first, so no foreign key is violated.
DELETE_ORDER = [
    "user_sessions",
    "users",
    "project_template_items",
    "prices",
    "materials",
    "categories",
    "suppliers",
]
COUNTED_TABLES = [*DELETE_ORDER, "order_items"]

USER_REFERENCES = [
    ("allocation_lines", "overridden_by_user_id"),
    ("orders", "created_by_user_id"),
    ("prices", "created_by_user_id"),
    ("projects", "created_by_user_id"),
    ("purchase_records", "created_by_user_id"),
    ("supplier_material_aliases", "created_by_user_id"),
]
MATERIAL_REFERENCES = [
    ("allocation_lines", "material_id"),
    ("order_items", "material_id"),
    ("price_list_entries", "matched_material_id"),
    ("project_items", "material_id"),
    ("purchase_records", "material_id"),
    ("supplier_material_aliases", "material_id"),
]
SUPPLIER_REFERENCES = [
    ("allocation_lines", "original_supplier_id"),
    ("allocation_lines", "supplier_id"),
    ("offices", "supplier_id"),
    ("orders", "supplier_id"),
    ("price_list_imports", "supplier_id"),
    ("purchase_records", "supplier_id"),
    ("supplier_contacts", "supplier_id"),
    ("supplier_material_aliases", "supplier_id"),
]


class CleanupRefused(Exception):
    """The database is not in the state this script was written for."""


@dataclass
class Plan:
    rows: dict[str, list[tuple]] = field(default_factory=dict)
    kept_suppliers: list[tuple] = field(default_factory=list)

    def ids(self, table: str) -> list:
        return [row[0] for row in self.rows[table]]


def _referencing_ids(connection: Connection, references: list, ids: list) -> dict:
    """Maps each referenced id to the `table.column` places that point at it."""
    found: dict = {}
    for table, column in references:
        rows = connection.execute(
            text(f"SELECT DISTINCT {column} FROM {table} WHERE {column} = ANY(:ids)"),
            {"ids": ids},
        )
        for (referenced_id,) in rows:
            found.setdefault(referenced_id, []).append(f"{table}.{column}")
    return found


def _check_target_is_the_dev_database(connection: Connection) -> None:
    database = connection.execute(text("SELECT current_database()")).scalar()
    host = connection.engine.url.host
    if database != DEV_DATABASE_NAME or host not in LOCAL_HOSTS:
        raise CleanupRefused(f"Refusing to run on database {database!r} at host {host!r}.")


def _check_protected_rows_exist(connection: Connection) -> None:
    admin = connection.execute(
        text("SELECT count(*) FROM users WHERE email = :email AND role = 'admin' AND is_active"),
        {"email": PROTECTED_EMAIL},
    ).scalar()
    categories = connection.execute(
        text("SELECT count(*) FROM categories WHERE name = ANY(:names)"),
        {"names": PROTECTED_CATEGORIES},
    ).scalar()
    order_item = connection.execute(
        text("SELECT count(*) FROM order_items WHERE id = :id"),
        {"id": PROTECTED_ORDER_ITEM_ID},
    ).scalar()
    if (admin, categories, order_item) != (1, len(PROTECTED_CATEGORIES), 1):
        raise CleanupRefused(
            "Protected rows are not all present: "
            f"admin={admin}, categories={categories}, order_item={order_item}."
        )


def _select(connection: Connection, sql: str, **params) -> list[tuple]:
    return [tuple(row) for row in connection.execute(text(sql), params)]


def build_plan(connection: Connection) -> Plan:
    plan = Plan()

    plan.rows["users"] = _select(
        connection,
        "SELECT id, email FROM users WHERE email = ANY(:emails) ORDER BY email",
        emails=TEST_USER_EMAILS,
    )
    user_ids = plan.ids("users")
    if PROTECTED_EMAIL in [email for _, email in plan.rows["users"]]:
        raise CleanupRefused("The protected administrator is in the delete list.")
    user_references = _referencing_ids(connection, USER_REFERENCES, user_ids)
    if user_references:
        raise CleanupRefused(f"Test users are referenced: {user_references}")
    plan.rows["user_sessions"] = _select(
        connection,
        """
        SELECT s.id, u.email FROM user_sessions s JOIN users u ON u.id = s.user_id
        WHERE s.user_id = ANY(:ids) ORDER BY u.email, s.id
        """,
        ids=user_ids,
    )

    plan.rows["categories"] = _select(
        connection,
        "SELECT id, name FROM categories WHERE name LIKE :pattern ORDER BY name",
        pattern=TEST_CATEGORY_PATTERN,
    )
    plan.rows["materials"] = _select(
        connection,
        """
        SELECT id, internal_sku, canonical_name FROM materials
        WHERE category_id = ANY(:ids) ORDER BY internal_sku
        """,
        ids=plan.ids("categories"),
    )
    not_test_data = [
        row
        for row in plan.rows["materials"]
        if row[2] != "Test Material" and not row[1].startswith("TEST-SKU-")
    ]
    if not_test_data:
        raise CleanupRefused(f"Materials that do not look like test data: {not_test_data}")
    material_ids = plan.ids("materials")
    material_references = _referencing_ids(connection, MATERIAL_REFERENCES, material_ids)
    if material_references:
        raise CleanupRefused(f"Test materials are referenced: {material_references}")

    plan.rows["prices"] = _select(
        connection,
        """
        SELECT p.id, m.internal_sku, p.supplier_id FROM prices p
        JOIN materials m ON m.id = p.material_id
        WHERE p.material_id = ANY(:ids) ORDER BY m.internal_sku, p.id
        """,
        ids=material_ids,
    )
    plan.rows["project_template_items"] = _select(
        connection,
        """
        SELECT i.id, t.name, m.internal_sku FROM project_template_items i
        JOIN project_templates t ON t.id = i.template_id
        JOIN materials m ON m.id = i.material_id
        WHERE i.material_id = ANY(:ids) ORDER BY t.name, i.id
        """,
        ids=material_ids,
    )

    candidates = _select(
        connection,
        """
        SELECT s.id, s.name,
               count(*) FILTER (WHERE p.material_id <> ALL(:ids)) AS other_prices
        FROM suppliers s JOIN prices p ON p.supplier_id = s.id
        WHERE s.id IN (SELECT supplier_id FROM prices WHERE material_id = ANY(:ids))
        GROUP BY s.id, s.name ORDER BY s.name, s.id
        """,
        ids=material_ids,
    )
    supplier_references = _referencing_ids(
        connection, SUPPLIER_REFERENCES, [row[0] for row in candidates]
    )
    plan.rows["suppliers"] = []
    for supplier_id, name, other_prices in candidates:
        removable = (
            name in TEST_SUPPLIER_NAMES
            and other_prices == 0
            and supplier_id not in supplier_references
        )
        (plan.rows["suppliers"] if removable else plan.kept_suppliers).append((supplier_id, name))
    return plan


def _counts(connection: Connection) -> dict[str, int]:
    return {
        table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        for table in COUNTED_TABLES
    }


def _print_plan(plan: Plan) -> None:
    for table in DELETE_ORDER:
        print(f"\n[{table}] {len(plan.rows[table])}")
        for row in plan.rows[table]:
            print("  " + " | ".join(str(value) for value in row))
    print(f"\n[suppliers kept] {len(plan.kept_suppliers)}")
    for row in plan.kept_suppliers:
        print("  " + " | ".join(str(value) for value in row))


def _print_counts(title: str, counts: dict[str, int]) -> None:
    print(f"\n{title}")
    for table, count in counts.items():
        print(f"  {table}: {count}")


def apply_plan(connection: Connection, plan: Plan, before: dict[str, int]) -> dict[str, int]:
    """Deletes the planned rows. Any exception rolls the whole transaction back."""
    for table in DELETE_ORDER:
        ids = plan.ids(table)
        deleted = connection.execute(
            text(f"DELETE FROM {table} WHERE id = ANY(:ids)"), {"ids": ids}
        ).rowcount
        if deleted != len(ids):
            raise CleanupRefused(f"{table}: planned {len(ids)}, deleted {deleted}.")

    after = _counts(connection)
    expected = {
        table: count - len(plan.rows.get(table, [])) for table, count in before.items()
    }
    if after != expected:
        raise CleanupRefused(f"Counts after delete: {after}, expected {expected}.")
    _check_protected_rows_exist(connection)
    return after


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="delete the listed rows")
    args = parser.parse_args()

    try:
        with engine.connect() as connection:
            with connection.begin() as transaction:
                if not args.apply:
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                _check_target_is_the_dev_database(connection)
                _check_protected_rows_exist(connection)
                plan = build_plan(connection)
                before = _counts(connection)
                _print_plan(plan)
                _print_counts("Counts before:", before)
                if not args.apply:
                    transaction.rollback()
                    print("\nDry run: nothing was changed. Use --apply to delete.")
                    return 0
                after = apply_plan(connection, plan, before)
    except CleanupRefused as refusal:
        print(f"\nREFUSED, nothing was changed: {refusal}", file=sys.stderr)
        return 1

    _print_counts("Counts after:", after)
    print("\nCommitted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
