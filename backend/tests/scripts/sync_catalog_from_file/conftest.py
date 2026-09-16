import datetime
import uuid

import openpyxl
import pytest

from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import Category, Material, Price, Supplier
from app.scripts import xlsx_price_matrix


@pytest.fixture
def patch_supplier_headers(monkeypatch):
    """SUPPLIER_COLUMN_HEADERS is a hardcoded dict of real supplier display
    names (EMS, Lancing, ...) -- tests must not use those names, since this
    suite runs against a shared dev DB that already has real Supplier rows
    with those names. Swaps in a test-only mapping so header->supplier-name
    resolution still exercises the real code path in xlsx_price_matrix.py/
    sync_catalog_from_file.py, just with collision-safe test data."""

    def _patch(mapping: dict[str, str]):
        monkeypatch.setattr(xlsx_price_matrix, "SUPPLIER_COLUMN_HEADERS", mapping)

    return _patch

_category_ids_pending_cleanup: list = []
"""Populated by make_category's own teardown when a Category delete can't
run yet (its materials aren't gone until db_session's teardown, which runs
AFTER make_category's -- pytest fixture teardown is LIFO, and make_category
depends on db_session). db_session's own teardown does the actual delete
once materials are cleaned up. Module-level and cleared at the start of each
db_session run so state never leaks between tests -- same pattern as
tests/price/conftest.py and tests/material/conftest.py."""


@pytest.fixture
def db_session():
    global _category_ids_pending_cleanup
    _category_ids_pending_cleanup = []
    session = SessionLocal()
    material_ids: list = []
    supplier_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, material_ids, supplier_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
        if material_ids:
            session.query(Price).filter(Price.material_id.in_(material_ids)).delete(
                synchronize_session=False
            )
            session.query(Material).filter(Material.id.in_(material_ids)).delete(
                synchronize_session=False
            )
        if supplier_ids:
            session.query(Price).filter(Price.supplier_id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
            session.query(Supplier).filter(Supplier.id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
        if _category_ids_pending_cleanup:
            session.query(Category).filter(
                Category.id.in_(_category_ids_pending_cleanup)
            ).delete(synchronize_session=False)
        session.commit()
        session.close()


@pytest.fixture
def make_category(db_session):
    session, *_ = db_session
    created_ids: list = []

    def _make(name=None, sku_prefix=None, requires_single_supplier=False, next_sku_number=1):
        name = name or f"Test Category {uuid.uuid4().hex[:12]}"
        sku_prefix = sku_prefix or f"TC{uuid.uuid4().hex[:6].upper()}"
        category = Category(
            name=name,
            sku_prefix=sku_prefix,
            requires_single_supplier=requires_single_supplier,
            next_sku_number=next_sku_number,
        )
        session.add(category)
        session.flush()
        created_ids.append(category.id)
        return category

    yield _make

    if created_ids:
        _category_ids_pending_cleanup.extend(created_ids)


@pytest.fixture
def make_material(db_session, make_category):
    session, material_ids, _supplier_ids = db_session

    def _make(sku=None, canonical_name=None, category=None, unit="ft", attributes=None):
        sku = sku or f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        if category is None:
            category = make_category()
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            category_id=category.id,
            unit=unit,
            attributes=attributes or {},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make


@pytest.fixture
def make_supplier(db_session):
    session, _material_ids, supplier_ids = db_session

    def _make(name="Test Supplier"):
        supplier = Supplier(name=name, currency="USD", delivery_policy={})
        session.add(supplier)
        session.flush()
        supplier_ids.append(supplier.id)
        return supplier

    return _make


@pytest.fixture
def make_price_matrix_xlsx(tmp_path):
    """Builds a minimal wide-matrix xlsx matching xlsx_price_matrix.py's
    expected layout (HEADER_ROW=1, FIRST_DATA_ROW=2, columns
    Group/Description/Quantity then one column per supplier header) so
    sync tests exercise parse_price_matrix() against a real file, not a
    hand-built ParsedWorkbook -- catches any drift between the two.

    rows: list of dicts, each with keys "group", "description", "quantity"
    and any of the supplier header strings (e.g. "EMS", "A&S") mapped to
    a price value or "" (blank cell) or omitted (no column value for that
    supplier on this row). supplier_headers: the exact header strings for
    columns 4+, in order -- lets tests exercise unmapped headers too.
    """

    def _make(rows: list[dict], supplier_headers: list[str], filename="test_price_matrix.xlsx"):
        wb = openpyxl.Workbook()
        ws = wb.active
        # Column A (index 0) is unused by parse_price_matrix -- COL_GROUP=1,
        # COL_DESCRIPTION=2, COL_QUANTITY=3 (0-indexed), so a real leading
        # blank column is required or every column shifts by one.
        header = ["", "Group", "Description", "Quantity", *supplier_headers]
        ws.append(header)
        for row in rows:
            line = ["", row.get("group", ""), row["description"], row.get("quantity", "1 pcs")]
            for supplier in supplier_headers:
                line.append(row.get(supplier, ""))
            ws.append(line)
        path = tmp_path / filename
        wb.save(path)
        return path

    return _make


@pytest.fixture
def make_price(db_session):
    session, *_ = db_session

    def _make(
        material,
        supplier,
        price=10.0,
        availability=100,
        min_order_qty=1,
        valid_from=None,
        valid_to=None,
    ):
        p = Price(
            material=material,
            supplier=supplier,
            price=price,
            currency="USD",
            availability=availability,
            min_order_qty=min_order_qty,
            valid_from=valid_from or datetime.date.today(),
            valid_to=valid_to,
        )
        session.add(p)
        session.flush()
        return p

    return _make
