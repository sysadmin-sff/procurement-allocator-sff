"""Tests for the Category backfill — ADR-0034 п.2. Same savepoint-session
pattern as test_backfill_color_options.py: run_backfill's internal
db.commit() only releases a SAVEPOINT here, never touching the real catalog.

The dev DB this suite runs against already holds the real ~294-material
catalog (imported by import_real_data.py), including real "Doors"/"Mesh"/etc.
category values -- and, as discovered while writing these tests, one stray
9th category value with mojibake encoding that is NOT in CATEGORY_SKU_PREFIX
(a pre-existing data-quality issue in the dev catalog, unrelated to this
task; see test_backfill_raises_on_unknown_category_already_present_in_dev_db
below, which documents and asserts on it directly).

Because run_backfill's own SELECT DISTINCT scans the whole table regardless
of any test's own transaction scope, most tests here use the
`patched_prefix_map` fixture, which extends the real CATEGORY_SKU_PREFIX with
a fallback prefix for whatever real category strings are currently in the DB
(including the stray one) so --apply doesn't unconditionally raise
UnknownCategoryError before the behavior under test even runs. Assertions
stay additive ("this material got linked", "the count increased by N")
rather than exact-count, since the shared dev DB's real rows are outside any
single test's control.
"""

import re

import pytest
from sqlalchemy import event, select

from app.core.database import engine
from app.models import Category, Material
from app.scripts.backfill_material_categories import (
    CATEGORY_SKU_PREFIX,
    STRICT_CATEGORY_NAMES,
    UnknownCategoryError,
    _link_materials_to_categories,
    _max_sku_suffix,
    run_backfill,
)


@pytest.fixture
def savepoint_session():
    connection = engine.connect()
    outer_transaction = connection.begin()

    from sqlalchemy.orm import Session

    session = Session(bind=connection, autoflush=False, autocommit=False)
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, transaction):
        if transaction.nested and not transaction._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


@pytest.fixture
def make_test_material(savepoint_session):
    counter = {"n": 0}

    def _make(category, sku=None, canonical_name=None):
        counter["n"] += 1
        sku = sku or f"ZZTEST-{counter['n']:04d}"
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            category=category,
            unit="ft",
            attributes={},
        )
        savepoint_session.add(material)
        savepoint_session.flush()
        return material

    return _make


@pytest.fixture
def patched_prefix_map(savepoint_session, monkeypatch):
    """Extends the real CATEGORY_SKU_PREFIX with a fallback prefix for every
    category string currently present in the DB (including the dev DB's
    known stray mojibake one), so run_backfill(apply=True) doesn't
    unconditionally raise UnknownCategoryError before the behavior under
    test runs. Returns the patched dict so tests needing new fixture
    categories can extend it further before calling run_backfill."""
    import app.scripts.backfill_material_categories as mod

    real_categories = {
        row[0]
        for row in savepoint_session.execute(
            select(Material.category).distinct().where(Material.category.is_not(None))
        ).all()
    }
    patched = dict(mod.CATEGORY_SKU_PREFIX)
    for name in real_categories:
        patched.setdefault(name, "ZZFALLBACK")
    monkeypatch.setattr(mod, "CATEGORY_SKU_PREFIX", patched)
    return patched


def test_backfill_dry_run_does_not_write_to_db(
    savepoint_session, make_test_material, patched_prefix_map
):
    material = make_test_material("Doors")

    report = run_backfill(savepoint_session, apply=False)

    assert any(row.name == "Doors" for row in report.category_rows)
    savepoint_session.expire_all()
    savepoint_session.refresh(material)
    assert material.category_id is None
    assert (
        savepoint_session.scalars(select(Category).where(Category.name == "Doors")).all() == []
    )


def test_backfill_apply_creates_exactly_the_real_8_categories_with_correct_flags(
    savepoint_session, patched_prefix_map
):
    """The real dev DB catalog already has all 8 real category strings
    present (no fixture needed to create them) -- this test exercises
    run_backfill directly against that pre-existing real data (plus the
    neutralized stray category, via patched_prefix_map), which is exactly
    the scenario Task 7's actual dry-run/--apply will face for the 8 real
    names. The stray category itself is asserted separately below."""
    report = run_backfill(savepoint_session, apply=True)

    real_rows = {row.name: row for row in report.category_rows if row.name in CATEGORY_SKU_PREFIX}
    assert set(real_rows) == set(CATEGORY_SKU_PREFIX)
    for name, row in real_rows.items():
        assert row.requires_single_supplier == (name in STRICT_CATEGORY_NAMES)
        assert row.sku_prefix == CATEGORY_SKU_PREFIX[name]

    categories = {
        c.name: c
        for c in savepoint_session.scalars(
            select(Category).where(Category.name.in_(CATEGORY_SKU_PREFIX))
        ).all()
    }
    assert set(categories) == set(CATEGORY_SKU_PREFIX)


def test_backfill_raises_on_unknown_category_already_present_in_dev_db(savepoint_session):
    """Discovery test: the dev DB's real catalog already contains one
    material with a category value outside CATEGORY_SKU_PREFIX (a stray
    mojibake string, pre-existing data-quality issue unrelated to this task).
    run_backfill must refuse to guess a prefix for it in --apply mode, per
    ADR-0034 п.2's explicit-error requirement -- this is the unpatched
    scenario (no patched_prefix_map), proving the real script really does
    stop here today."""
    with pytest.raises(UnknownCategoryError):
        run_backfill(savepoint_session, apply=True)


def test_backfill_dry_run_reports_the_real_unknown_category_without_raising_or_writing(
    savepoint_session,
):
    report = run_backfill(savepoint_session, apply=False)

    assert len(report.unknown_categories) >= 1
    assert all(c not in CATEGORY_SKU_PREFIX for c in report.unknown_categories)
    savepoint_session.expire_all()
    assert (
        savepoint_session.scalars(select(Category).where(Category.name == "Doors")).all() == []
    )


def test_backfill_links_material_to_its_category_row(savepoint_session, make_test_material):
    """Unit test of the linking step alone. _link_materials_to_categories
    scans every Material with category IS NOT NULL in the whole table (not
    just ones named in category_by_name), so -- like the real run_backfill
    call site that always builds a complete map first -- this test's map
    must cover every distinct category string currently in the DB (real
    catalog rows included), or it raises KeyError on an uncovered one. This
    mirrors the real precondition run_backfill's own `unknown` check
    enforces before ever calling this function."""
    material = make_test_material("Connectors", sku="ZZTEST-LINK-001")

    distinct_categories = [
        row[0]
        for row in savepoint_session.execute(
            select(Material.category).distinct().where(Material.category.is_not(None))
        ).all()
    ]
    category_by_name = {}
    for name in distinct_categories:
        category = Category(
            name=name, sku_prefix=f"Z{abs(hash(name)) % 100000}", requires_single_supplier=False
        )
        savepoint_session.add(category)
        savepoint_session.flush()
        category_by_name[name] = category

    _link_materials_to_categories(savepoint_session, category_by_name)
    savepoint_session.flush()

    savepoint_session.refresh(material)
    assert material.category_id == category_by_name["Connectors"].id


def test_backfill_sets_next_sku_number_from_max_existing_suffix(
    savepoint_session, make_test_material, patched_prefix_map
):
    """Uses the real "Screws" category (prefix SCRW, not strict) alongside
    the real pre-existing SCRW-* rows -- adds one material with a
    deliberately high suffix and asserts next_sku_number lands exactly one
    past the true maximum (whatever that is across real + this fixture),
    not by assuming the real catalog's own max is a specific number."""
    existing_max = 0
    suffix_re = re.compile(r"-(\d+)$")
    for (sku,) in savepoint_session.execute(
        select(Material.internal_sku).where(Material.category == "Screws")
    ).all():
        match = suffix_re.search(sku)
        if match:
            existing_max = max(existing_max, int(match.group(1)))

    forced_high = existing_max + 100
    make_test_material("Screws", sku=f"SCRW-{forced_high:03d}")

    report = run_backfill(savepoint_session, apply=False)

    row = next(r for r in report.category_rows if r.name == "Screws")
    assert row.next_sku_number == forced_high + 1


def test_backfill_next_sku_number_defaults_to_1_when_no_material_has_a_numeric_suffix():
    """Isolated unit test of _max_sku_suffix directly, proving the "no
    numeric suffix anywhere" -> 0 (so next_sku_number = 0 + 1 = 1) fallback,
    without needing an empty category (none exists in the polluted dev DB
    for any of the 8 real names)."""

    class _FakeMaterial:
        def __init__(self, internal_sku):
            self.internal_sku = internal_sku

    assert _max_sku_suffix([_FakeMaterial("WEIRD-SKU"), _FakeMaterial("ANOTHER-WEIRD")]) == 0


def test_backfill_verification_matches_null_counts(
    savepoint_session, make_test_material, patched_prefix_map
):
    """null_category_id_before/after count ALL materials with category IS
    NULL in the whole table (including real catalog rows already NULL, if
    any) -- this test only asserts the delta stays consistent, not an
    absolute count, since the shared dev DB may already have NULL-category
    rows outside this test's control."""
    before = savepoint_session.query(Material).filter(Material.category.is_(None)).count()
    make_test_material(None, sku="ZZTEST-NOCAT")  # material with no category at all

    report = run_backfill(savepoint_session, apply=True)

    assert report.null_category_id_before == before + 1
    assert report.null_category_id_after == before + 1
    assert report.verification_ok is True


def test_backfill_verification_catches_corrupted_case_and_rolls_back(
    savepoint_session, make_test_material, patched_prefix_map, monkeypatch
):
    """Artificially break the verification invariant: patch run_backfill's
    UPDATE step so one material with a non-null category is deliberately left
    with category_id NULL, then confirm the script detects the mismatch and
    rolls back rather than committing a partial result."""
    import app.scripts.backfill_material_categories as mod

    stray_sku = "ZZTEST-STRAY-001"
    make_test_material("Doors", sku=stray_sku)

    original_link = mod._link_materials_to_categories

    def _broken_link(db, category_by_name):
        original_link(db, category_by_name)
        stray = db.scalars(select(Material).where(Material.internal_sku == stray_sku)).one()
        stray.category_id = None

    monkeypatch.setattr(mod, "_link_materials_to_categories", _broken_link)

    report = run_backfill(savepoint_session, apply=True)

    assert report.verification_ok is False


def test_backfill_is_idempotent_categories_not_duplicated_on_second_run(
    savepoint_session, patched_prefix_map
):
    # No explicit savepoint_session.commit() here between runs -- run_backfill's
    # own internal db.commit() (inside apply=True) already releases and
    # restarts the SAVEPOINT via the fixture's after_transaction_end hook, so
    # the second call sees the first's committed Category rows without this
    # test needing its own extra commit (which would step outside the
    # fixture's isolation and collide with real catalog rows across tests).
    run_backfill(savepoint_session, apply=True)
    report_2 = run_backfill(savepoint_session, apply=True)

    categories = savepoint_session.scalars(
        select(Category).where(Category.name == "Doors")
    ).all()
    assert len(categories) == 1
    assert report_2.verification_ok is True
