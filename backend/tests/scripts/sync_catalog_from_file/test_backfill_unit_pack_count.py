"""Tests for backfill_unit_pack_count.py (ADR-0036) — the reviewed, explicit
backfill for Material.unit rows corrupted by the pre-fix _clean_unit bug
("1 sq ft" instead of "sq ft"). Reuses sync_catalog_from_file's test
fixtures (db_session, make_category, make_material, make_price_matrix_xlsx)
since both scripts share the same xlsx-matching machinery."""

from app.scripts.backfill_unit_pack_count import apply_unit_backfill, plan_unit_backfill


def test_corrects_material_whose_stored_unit_is_uncleaned_pack_of_one(
    db_session, make_category, make_material, make_price_matrix_xlsx, patch_supplier_headers
):
    session, *_ = db_session
    patch_supplier_headers({})
    category = make_category(name="Backfill Test Category")
    material = make_material(
        canonical_name="Backfill Test Roof Panel",
        category=category,
        unit="1 sq ft",  # the pre-fix, uncleaned shape
    )

    path = make_price_matrix_xlsx(
        rows=[
            {
                "group": category.name,
                "description": "Backfill Test Roof Panel",
                "quantity": "1 sq ft",
            }
        ],
        supplier_headers=[],
    )

    report = plan_unit_backfill(session, path)

    assert len(report.corrected) == 1
    row = report.corrected[0]
    assert row.material_sku == material.internal_sku
    assert row.old_unit == "1 sq ft"
    assert row.new_unit == "sq ft"
    assert report.unconfirmed == []

    # Dry-run by default -- plan alone must not touch the DB.
    session.refresh(material)
    assert material.unit == "1 sq ft"

    apply_unit_backfill(session, report)
    session.refresh(material)
    assert material.unit == "sq ft"


def test_does_not_touch_pack_count_other_than_one(
    db_session, make_category, make_material, make_price_matrix_xlsx, patch_supplier_headers
):
    """"5 box" is real pack-size information, not the uninformative "1 "
    this backfill targets -- same rule as _clean_unit/ADR-0036."""
    session, *_ = db_session
    patch_supplier_headers({})
    category = make_category(name="Backfill Test Category 2")
    make_material(
        canonical_name="Backfill Test Box Item",
        category=category,
        unit="5 box",
    )
    box_row = {"group": category.name, "description": "Backfill Test Box Item", "quantity": "5 box"}
    make_price_matrix_xlsx(rows=[box_row], supplier_headers=[])
    path = make_price_matrix_xlsx(rows=[box_row], supplier_headers=[], filename="second.xlsx")

    report = plan_unit_backfill(session, path)

    assert report.corrected == []
    assert report.unconfirmed == []


def test_already_clean_unit_is_not_a_candidate(
    db_session, make_category, make_material, make_price_matrix_xlsx, patch_supplier_headers
):
    session, *_ = db_session
    patch_supplier_headers({})
    category = make_category(name="Backfill Test Category 3")
    make_material(canonical_name="Backfill Test Clean Item", category=category, unit="sq ft")
    clean_row = {
        "group": category.name,
        "description": "Backfill Test Clean Item",
        "quantity": "1 sq ft",
    }
    path = make_price_matrix_xlsx(rows=[clean_row], supplier_headers=[])

    report = plan_unit_backfill(session, path)

    assert report.corrected == []
    assert report.unconfirmed == []


def test_pack_of_one_shaped_unit_not_confirmed_by_file_is_left_unconfirmed(
    db_session, make_category, make_material, make_price_matrix_xlsx, patch_supplier_headers
):
    """A material shaped like "1 <unit>" that the file doesn't back up (no
    matching row, or the file now says something else) must not be
    silently corrected -- flagged for manual review instead."""
    session, *_ = db_session
    patch_supplier_headers({})
    category = make_category(name="Backfill Test Category 4")
    material = make_material(
        canonical_name="Backfill Test Orphan Item",
        category=category,
        unit="1 crate",
    )
    path = make_price_matrix_xlsx(rows=[], supplier_headers=[])

    report = plan_unit_backfill(session, path)

    assert report.corrected == []
    assert report.unconfirmed == [material.internal_sku]
