"""Tests for audit_min_order_qty.py -- see ADR-0045 §План выкатки п.2.

Runs against the real configured DB (SessionLocal), same as the other
tests under tests/scripts/ -- there is no sqlite/mocked-session path in
this codebase, so these require a reachable Postgres (dev DB or
docker compose, matching settings.database_url), not a mock.
"""

import csv

import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError

from app.scripts.audit_min_order_qty import (
    collect_min_order_qty_rows,
    print_report,
    write_csv,
)


def test_collect_only_returns_active_rows_with_min_order_qty_set(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    material_a = make_material(canonical_name="MOQ Audit Fastener No MOQ")
    material_b = make_material(canonical_name="MOQ Audit Fastener With MOQ")
    supplier = make_supplier()
    no_moq = make_price(material_a, supplier, min_order_qty=None)
    with_moq = make_price(material_b, supplier, min_order_qty=100)

    rows = collect_min_order_qty_rows(session)
    row_ids = {r.price_id for r in rows}
    assert with_moq.id in row_ids
    assert no_moq.id not in row_ids


def test_audit_never_commits_or_mutates_rows(db_session, make_material, make_supplier, make_price):
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()
    price = make_price(material, supplier, min_order_qty=50)

    collect_min_order_qty_rows(session)

    session.expire_all()
    assert price.min_order_qty == 50


def test_price_id_appears_in_console_report(
    db_session, make_material, make_supplier, make_price, capsys
):
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()
    price = make_price(material, supplier, min_order_qty=100)

    rows = collect_min_order_qty_rows(session)
    rows = [r for r in rows if r.price_id == price.id]
    assert len(rows) == 1

    print_report(rows)
    captured = capsys.readouterr()
    assert str(price.id) in captured.out


def test_price_id_is_first_csv_column_and_present_in_rows(
    db_session, make_material, make_supplier, make_price, tmp_path
):
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()
    price = make_price(material, supplier, min_order_qty=100)

    rows = collect_min_order_qty_rows(session)
    rows = [r for r in rows if r.price_id == price.id]
    assert len(rows) == 1

    csv_path = tmp_path / "audit.csv"
    write_csv(rows, str(csv_path))

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        data_row = next(reader)

    assert header[0] == "price_id"
    assert data_row[0] == str(price.id)


def test_transaction_is_read_only_after_collect(
    db_session, make_material, make_supplier, make_price
):
    """SET TRANSACTION READ ONLY must actually block a write attempted in
    the same session/transaction after collect_min_order_qty_rows runs --
    not just rely on this script's own code never calling commit(). The
    target row is created and flushed BEFORE collect() runs (flush is a
    write too -- it would itself be blocked if attempted after the
    READ ONLY guard, which is exactly the property being tested, so it
    must happen first), then collect() sets the transaction read-only, then
    a plain UPDATE on that same already-existing row is attempted and must
    fail."""
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()
    price = make_price(material, supplier, min_order_qty=100)

    collect_min_order_qty_rows(session)

    with pytest.raises(InternalError) as exc_info:
        session.execute(
            text("UPDATE prices SET min_order_qty = 999 WHERE id = :pid"),
            {"pid": str(price.id)},
        )
    message = str(exc_info.value).lower()
    assert "read-only" in message or "readonlysqltransaction" in message
    session.rollback()


def test_price_is_decimal_formatted_on_fresh_read(
    db_session, make_material, make_supplier, make_price
):
    """Proves str(), not float(), matters: Price.price is NUMERIC(12,3).
    Reading it through a genuinely FRESH session (not the one that created
    the row, so no identity-map shortcut -- this is what a real one-shot
    `python -m app.scripts.audit_min_order_qty` invocation always does,
    since it never shares a session with whatever process wrote the data)
    returns Decimal('12.500'), not float 12.5.

    12.5 (not 12.375) is the value that actually distinguishes str() from
    float() here: 12.375 = 12 + 3/8 is exactly representable in binary
    float, so str(Decimal("12.375")) == str(float(Decimal("12.375")))
    trivially -- that value could not have caught a str()-to-float()
    regression, which was a mistake in an earlier version of this test.
    12.500's trailing zero is NUMERIC(12,3) scale information that float()
    discards: float(Decimal("12.500")) == 12.5, str() of which is "12.5",
    losing the column's actual precision. str(Decimal("12.500")) == "12.500" is
    the value this test asserts collect_min_order_qty_rows must produce."""
    from app.core.database import SessionLocal

    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()
    price = make_price(material, supplier, price=12.5, min_order_qty=100)
    session.commit()

    fresh = SessionLocal()
    try:
        rows = collect_min_order_qty_rows(fresh)
        rows = [r for r in rows if r.price_id == price.id]
        assert len(rows) == 1
        assert rows[0].price == "12.500"
    finally:
        fresh.close()


def test_csv_row_aligns_with_all_twelve_header_columns(
    db_session, make_material, make_supplier, make_price, make_price_list_import, tmp_path
):
    session, *_ = db_session
    material = make_material(canonical_name="MOQ Audit CSV Alignment Material")
    supplier = make_supplier(name="MOQ Audit CSV Alignment Supplier")
    price_list_import = make_price_list_import(supplier=supplier)
    price = make_price(
        material,
        supplier,
        price=12.5,
        availability=42,
        min_order_qty=100,
        source_import_id=price_list_import.id,
    )

    rows = collect_min_order_qty_rows(session)
    rows = [r for r in rows if r.price_id == price.id]
    assert len(rows) == 1

    csv_path = tmp_path / "audit_full.csv"
    write_csv(rows, str(csv_path))

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        data_row = next(reader)

    expected_header = [
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
    assert header == expected_header
    assert len(data_row) == len(expected_header) == 12

    by_column = dict(zip(header, data_row, strict=True))
    assert by_column["price_id"] == str(price.id)
    assert by_column["supplier_name"] == supplier.name
    assert by_column["material_internal_sku"] == material.internal_sku
    assert by_column["material_canonical_name"] == material.canonical_name
    assert by_column["min_order_qty"] == "100"
    assert by_column["unit"] == material.unit
    # NOT "12.500": collect_min_order_qty_rows runs in the SAME session
    # that created this fixture row, so SQLAlchemy's identity map hands
    # back the exact in-memory Price object make_price constructed --
    # price.price is still the raw Python float literal (12.5) passed to
    # the constructor, never round-tripped through NUMERIC(12,3) within
    # this session. A real one-shot script invocation never hits this
    # (every row was written by a different process/session, so there is
    # no identity-map shortcut) -- confirmed separately: a fresh
    # select(Price.price) issued by an unrelated session on this same row
    # returns Decimal('12.500'). This assertion documents str(), not
    # float(), is still used (str(12.5) == "12.5", str(float(12.5)) is
    # identical here, so this alone would not catch a float() regression
    # -- see test_price_is_decimal_formatted_on_fresh_read below for that).
    assert by_column["price"] == "12.5"
    assert by_column["currency"] == "USD"
    assert by_column["availability"] == "42"
    assert by_column["valid_from"] == price.valid_from.isoformat()
    assert by_column["supplier_is_active_for_allocation"] == "True"
    assert by_column["likely_from_pdf_import"] == "True"
