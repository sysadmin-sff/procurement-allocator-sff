"""Tests for sync_catalog_from_file.py — see ADR-0035. Full spec of required
cases is enumerated in the ADR's "Последствия" section; each test here maps
to one bullet there.

SUPPLIER_COLUMN_HEADERS (xlsx_price_matrix.py) is a hardcoded dict of real
supplier display names -- tests must not use those names directly (EMS,
Lancing, ...) since this suite runs against a shared dev DB that already has
real Supplier rows with those names (see docs/known-issues.md). Every test
patches SUPPLIER_COLUMN_HEADERS to a test-only mapping via the
patch_supplier_headers fixture so file-header-to-supplier-name resolution
still goes through the real dict lookup path, just with safe test data.
"""

import pytest

from app.scripts.sync_catalog_from_file import SyncVerificationError, run_sync


def test_matched_material_price_differs_goes_to_price_updates(
    db_session,
    make_category,
    make_material,
    make_supplier,
    make_price,
    make_price_matrix_xlsx,
    patch_supplier_headers,
):
    session, *_ = db_session
    patch_supplier_headers({"Sync Test EMS": "Sync Test EMS"})
    category = make_category()
    material = make_material(canonical_name="Sync Test Door Handle", category=category)
    supplier = make_supplier(name="Sync Test EMS")
    make_price(material, supplier, price=10.00)

    path = make_price_matrix_xlsx(
        rows=[
            {
                "group": category.name,
                "description": "Sync Test Door Handle",
                "Sync Test EMS": 12.50,
            }
        ],
        supplier_headers=["Sync Test EMS"],
    )

    report = run_sync(session, path, apply=False)

    assert len(report.price_updates) == 1
    row = report.price_updates[0]
    assert row.material_id == material.id
    assert row.supplier_id == supplier.id
    assert row.old_price == 10.00
    assert row.new_price == 12.50
    assert report.price_closures == []
    assert report.price_creations == []


def test_whitespace_normalization_matches_extra_spaces(
    db_session, make_category, make_material, make_price_matrix_xlsx, patch_supplier_headers
):
    """ADR-0035 §1: strip + collapse internal whitespace runs, so extra
    spaces (accidental Excel copy-paste noise) don't prevent a match."""
    session, *_ = db_session
    patch_supplier_headers({})
    category = make_category()
    material = make_material(canonical_name="Sync  Test   Door  Handle", category=category)

    path = make_price_matrix_xlsx(
        rows=[{"group": category.name, "description": "  Sync Test Door Handle  "}],
        supplier_headers=[],
    )

    report = run_sync(session, path, apply=False)

    assert report.unmatched_price_rows == []
    assert material.internal_sku not in report.not_in_file


def test_casing_difference_does_not_match(
    db_session, make_category, make_material, make_price_matrix_xlsx, patch_supplier_headers
):
    """ADR-0035 §1: no casefold — a casing-only difference is NOT the same
    material as far as this script is concerned, must go to
    unmatched_price_rows (an unresolvable file category isolates this case
    from the separate new-material-creation path, which has its own test)."""
    session, *_ = db_session
    patch_supplier_headers({})
    category = make_category()
    make_material(canonical_name="Door Handle", category=category)

    path = make_price_matrix_xlsx(
        rows=[{"group": "Nonexistent Category For Casing Test", "description": "DOOR HANDLE"}],
        supplier_headers=[],
    )

    report = run_sync(session, path, apply=False)

    assert len(report.unmatched_price_rows) == 1
    assert report.unmatched_price_rows[0].description == "DOOR HANDLE"
    assert len(report.unresolved_category_rows) == 1
    assert report.new_materials == []


def test_empty_cell_closes_active_price_without_creating_new(
    db_session,
    make_category,
    make_material,
    make_supplier,
    make_price,
    make_price_matrix_xlsx,
    patch_supplier_headers,
):
    """ADR-0035 §2б: blank cell + existing active Price -> close it, no
    replacement created. Regression test for the ADR's key decision."""
    session, *_ = db_session
    patch_supplier_headers({"Sync Test EMS": "Sync Test EMS"})
    category = make_category()
    material = make_material(canonical_name="Sync Test Blank Cell Material", category=category)
    supplier = make_supplier(name="Sync Test EMS")
    make_price(material, supplier, price=15.00)

    path = make_price_matrix_xlsx(
        rows=[
            {
                "group": category.name,
                "description": "Sync Test Blank Cell Material",
                "Sync Test EMS": "",
            }
        ],
        supplier_headers=["Sync Test EMS"],
    )

    report = run_sync(session, path, apply=False)

    assert len(report.price_closures) == 1
    row = report.price_closures[0]
    assert row.material_id == material.id
    assert row.supplier_id == supplier.id
    assert row.closed_price == 15.00
    assert report.price_updates == []
    assert report.price_creations == []


def test_matched_material_with_category_and_unit_mismatch_not_changed(
    db_session,
    make_category,
    make_material,
    make_price_matrix_xlsx,
    patch_supplier_headers,
):
    """ADR-0035 §2.1: category_id/unit of a matched Material are NEVER
    changed by this script, no matter what the file says — only reported."""
    session, *_ = db_session
    patch_supplier_headers({})
    db_category = make_category(name="Sync Test DB Category")
    file_category = make_category(name="Sync Test File Category")
    material = make_material(
        canonical_name="Sync Test Mismatch Material",
        category=db_category,
        unit="ft",
    )

    path = make_price_matrix_xlsx(
        rows=[
            {
                "group": file_category.name,
                "description": "Sync Test Mismatch Material",
                "quantity": "5 box",
            }
        ],
        supplier_headers=[],
    )

    report = run_sync(session, path, apply=False)

    assert material.category_id == db_category.id
    assert material.unit == "ft"
    assert len(report.category_or_unit_mismatches) == 1
    row = report.category_or_unit_mismatches[0]
    assert row.material_id == material.id
    assert row.current_category_name == "Sync Test DB Category"
    assert row.file_category_name == "Sync Test File Category"
    assert row.current_unit == "ft"
    assert row.file_unit == "5 box"


def test_new_material_with_resolvable_category_predicts_sku_in_dry_run(
    db_session, make_category, make_price_matrix_xlsx, patch_supplier_headers
):
    """ADR-0035 §3: unmatched row whose Group resolves to an existing
    Category becomes a new_materials row with a predicted SKU (dry-run
    reads Category.next_sku_number without calling generate_next_sku)."""
    session, *_ = db_session
    patch_supplier_headers({"Sync Test EMS": "Sync Test EMS"})
    category = make_category(sku_prefix="SYNT", next_sku_number=5)

    path = make_price_matrix_xlsx(
        rows=[
            {
                "group": category.name,
                "description": "Sync Test Brand New Material",
                "Sync Test EMS": 3.75,
            }
        ],
        supplier_headers=["Sync Test EMS"],
    )

    report = run_sync(session, path, apply=False)

    assert len(report.new_materials) == 1
    row = report.new_materials[0]
    assert row.category_name == category.name
    assert row.predicted_sku == "SYNT-005"
    assert row.canonical_name == "Sync Test Brand New Material"
    assert row.material_id is None
    assert len(report.price_creations) == 1


def test_new_material_with_unknown_category_not_created(
    db_session, make_price_matrix_xlsx, patch_supplier_headers
):
    """ADR-0035 §3: unresolved category -> unresolved_category_rows, no
    Material created, not even a tentative one."""
    session, *_ = db_session
    patch_supplier_headers({})

    path = make_price_matrix_xlsx(
        rows=[
            {
                "group": "Sync Test Totally Unknown Category",
                "description": "Sync Test Orphan Material",
            }
        ],
        supplier_headers=[],
    )

    report = run_sync(session, path, apply=False)

    assert report.new_materials == []
    assert len(report.unresolved_category_rows) == 1
    assert report.unresolved_category_rows[0].category == "Sync Test Totally Unknown Category"


def test_new_supplier_created_with_default_delivery_policy_on_apply(
    db_session, make_category, make_material, make_price_matrix_xlsx, patch_supplier_headers
):
    """ADR-0035 §5: a header IN SUPPLIER_COLUMN_HEADERS but with no matching
    Supplier row yet is created with DEFAULT_DELIVERY_POLICY and listed in
    new_suppliers -- only on --apply, dry-run only reports the name."""
    import uuid as _uuid

    from app.models import Price, Supplier
    from app.scripts.import_real_data import DEFAULT_DELIVERY_POLICY

    session, *_ = db_session
    # Unique per test run -- this Supplier is created by run_sync itself,
    # not tracked by db_session's own supplier_ids cleanup list, so a fixed
    # name would collide with debris left behind by an interrupted prior
    # run of this same test (as actually happened while developing this
    # test: an assertion failure before the try/finally below existed left
    # a real row that broke the next run's "must not exist yet" assertion).
    supplier_name = f"Sync Test New Supplier {_uuid.uuid4().hex[:8]}"
    patch_supplier_headers({supplier_name: supplier_name})
    category = make_category()
    make_material(canonical_name="Sync Test New Supplier Material", category=category)

    path = make_price_matrix_xlsx(
        rows=[
            {
                "group": category.name,
                "description": "Sync Test New Supplier Material",
                supplier_name: 8.00,
            }
        ],
        supplier_headers=[supplier_name],
    )

    try:
        dry_run_report = run_sync(session, path, apply=False)
        assert dry_run_report.new_suppliers == [supplier_name]
        assert (
            session.query(Supplier).filter_by(name=supplier_name).first() is None
        ), "dry-run must not create the Supplier"

        apply_report = run_sync(session, path, apply=True)
        assert apply_report.new_suppliers == [supplier_name]
        created = session.query(Supplier).filter_by(name=supplier_name).one()
        assert created.delivery_policy == DEFAULT_DELIVERY_POLICY
    finally:
        # This Supplier (and any Price against it) isn't tracked by
        # db_session's own supplier_ids list -- clean it up regardless of
        # whether the assertions above passed.
        session.rollback()
        supplier_row = session.query(Supplier).filter_by(name=supplier_name).first()
        if supplier_row is not None:
            session.query(Price).filter_by(supplier_id=supplier_row.id).delete()
            session.query(Supplier).filter_by(id=supplier_row.id).delete()
            session.commit()


def test_material_absent_from_file_is_not_touched(
    db_session,
    make_category,
    make_material,
    make_supplier,
    make_price,
    make_price_matrix_xlsx,
    patch_supplier_headers,
):
    """ADR-0035 §4: a Material with no matching row anywhere in the file is
    never modified, never deactivated -- only listed in not_in_file. None of
    its Prices are closed either, regardless of supplier."""
    session, *_ = db_session
    patch_supplier_headers({})
    category = make_category()
    material = make_material(canonical_name="Sync Test Absent Material", category=category)
    supplier = make_supplier(name="Sync Test Absent Supplier")
    make_price(material, supplier, price=20.00)

    path = make_price_matrix_xlsx(
        rows=[{"group": category.name, "description": "Some Other Material Entirely"}],
        supplier_headers=[],
    )

    report = run_sync(session, path, apply=False)

    assert material.internal_sku in report.not_in_file
    assert report.price_closures == []
    active = (
        session.query(type(material).prices.property.mapper.class_)
        .filter_by(material_id=material.id, supplier_id=supplier.id, valid_to=None)
        .first()
    )
    assert active is not None
    assert float(active.price) == 20.00


def test_dry_run_never_writes_to_db_including_sku_counter(
    db_session, make_category, make_price_matrix_xlsx, patch_supplier_headers
):
    """ADR-0035 §7: dry-run must not call db.commit() at all, including not
    incrementing Category.next_sku_number via generate_next_sku()."""
    session, *_ = db_session
    patch_supplier_headers({"Sync Test EMS": "Sync Test EMS"})
    category = make_category(sku_prefix="SYNT2", next_sku_number=1)

    path = make_price_matrix_xlsx(
        rows=[
            {
                "group": category.name,
                "description": "Sync Test Dry Run Material",
                "Sync Test EMS": 6.00,
            }
        ],
        supplier_headers=["Sync Test EMS"],
    )

    run_sync(session, path, apply=False)

    session.expire(category)
    assert category.next_sku_number == 1, "dry-run must not increment next_sku_number"
    from app.models import Material

    assert (
        session.query(Material).filter_by(canonical_name="Sync Test Dry Run Material").first()
        is None
    ), "dry-run must not create the Material"


def test_apply_verification_mismatch_rolls_back_entire_transaction(
    db_session,
    make_category,
    make_material,
    make_supplier,
    make_price,
):
    """ADR-0035 §8: if the count of applied changes doesn't match the
    report's own counts, _verify_and_finalize rolls back the WHOLE
    transaction, not just the mismatched row -- tested directly against the
    real function with an artificially corrupted report.count, rather than
    going through run_sync's own (correct) counting, which the "happy path"
    tests already cover."""
    from app.scripts.sync_catalog_from_file import (
        PriceUpdateRow,
        SyncReport,
        _verify_and_finalize,
        version_price,
    )

    session, *_ = db_session
    category = make_category()
    material = make_material(canonical_name="Sync Test Rollback Material", category=category)
    supplier = make_supplier(name="Sync Test Rollback Supplier")
    make_price(material, supplier, price=1.00)
    # Commit the setup so the assertion below can distinguish "the mismatch
    # rollback undid only the change under test" from "the whole session's
    # uncommitted work vanished" -- without this, _verify_and_finalize's
    # own db.rollback() would also undo this fixture data (it was only
    # flushed, not committed), making the test unable to tell the two cases
    # apart.
    session.commit()

    # Apply one real price change (as run_sync's apply=True path would),
    # then hand-build a report that claims TWO changes happened -- an
    # artificial undercount of what was actually applied, the exact defect
    # this verification step exists to catch.
    version_price(
        session, material_id=material.id, supplier_id=supplier.id, price=99.00, commit=False
    )
    report = SyncReport(dry_run=False)
    report.price_updates = [
        PriceUpdateRow(
            material_id=material.id,
            material_sku=material.internal_sku,
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            old_price=1.00,
            new_price=99.00,
        ),
        PriceUpdateRow(
            material_id=material.id,
            material_sku=material.internal_sku,
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            old_price=1.00,
            new_price=99.00,
        ),
    ]
    report.applied_price_change_count = 1  # only one really happened above

    material_id = material.id
    supplier_id = supplier.id

    with pytest.raises(SyncVerificationError):
        _verify_and_finalize(session, report)

    assert report.verification_ok is False

    # _verify_and_finalize already rolled back -- material/supplier are
    # detached from this Session now, so re-query by id rather than
    # touching the stale ORM objects.
    from app.models import Price

    active_prices = (
        session.query(Price)
        .filter_by(material_id=material_id, supplier_id=supplier_id, valid_to=None)
        .all()
    )
    assert len(active_prices) == 1
    assert float(active_prices[0].price) == 1.00, (
        "verification failure must roll back the price update entirely, "
        "leaving the ORIGINAL price untouched"
    )
