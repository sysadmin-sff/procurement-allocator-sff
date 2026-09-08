"""Tests for the one-time color backfill script — see ADR-0031 п.1.

run_backfill scans the *entire* materials table (color_options IS NULL) by
design, and the dev DB used elsewhere in this suite already holds the real
~294-material catalog (imported by import_real_data.py) — so an apply=True
test here would otherwise write color_options/color_fragment onto real
catalog rows as a side effect, even though the test only cares about its own
fixture row. Every test in this module runs inside its own SAVEPOINT
(nested transaction) that is rolled back on teardown, so run_backfill's
internal db.commit() only releases the savepoint rather than committing to
the real database — the standard SQLAlchemy pattern for isolating a test
that itself calls commit(). See:
https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites
"""

import pytest
from sqlalchemy import event

from app.core.database import engine
from app.models import Material
from app.scripts.backfill_color_options import run_backfill


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

    def _make(sku, canonical_name, color_options=None, color_fragment=None):
        counter["n"] += 1
        kwargs = {}
        # Only pass color_options/color_fragment when actually setting a
        # value — SQLAlchemy's JSON type writes a literal JSON "null" (not
        # SQL NULL) for an explicitly-assigned None, which would make
        # run_backfill's `color_options IS NULL` filter skip this row. See
        # ADR-0031 п.1 backfill's NULL-scan contract; omitting the kwarg
        # entirely lets the column's real NULL default apply, matching how
        # every material created without touching these fields behaves.
        if color_options is not None:
            kwargs["color_options"] = color_options
        if color_fragment is not None:
            kwargs["color_fragment"] = color_fragment
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name,
            unit="ft",
            attributes={},
            **kwargs,
        )
        savepoint_session.add(material)
        savepoint_session.flush()
        return material

    return _make


def _row_for(report, sku):
    return next((r for r in report.recognized if r.internal_sku == sku), None)


def test_backfill_dry_run_does_not_write_to_db(savepoint_session, make_test_material):
    material = make_test_material("GUTR-DRY", 'Super Gutter End Cap 5" (White/Bronze)')

    report = run_backfill(savepoint_session, apply=False)

    row = _row_for(report, "GUTR-DRY")
    assert row is not None
    assert row.color_options == ["White", "Bronze"]
    savepoint_session.expire_all()
    savepoint_session.refresh(material)
    assert material.color_options is None
    assert material.color_fragment is None


def test_backfill_apply_writes_to_db(savepoint_session, make_test_material):
    material = make_test_material("GUTR-APPLY", 'Super Gutter End Cap 5" (White/Bronze)')

    run_backfill(savepoint_session, apply=True)

    savepoint_session.refresh(material)
    assert material.color_options == ["White", "Bronze"]
    assert material.color_fragment == "(White/Bronze)"


def test_backfill_bare_screws_format(savepoint_session, make_test_material):
    material = make_test_material("SCRW-BARE", '12 x 3/4" Bronze/White Stainless steel')

    report = run_backfill(savepoint_session, apply=True)

    savepoint_session.refresh(material)
    assert material.color_options == ["Bronze", "White"]
    assert material.color_fragment == "Bronze/White"
    row = _row_for(report, "SCRW-BARE")
    assert row is not None
    assert row.pattern == "bare"


def test_backfill_single_color_parens_not_recognized(savepoint_session, make_test_material):
    material = make_test_material("EFAS-1", "E-Fascia x 24' (White)")

    report = run_backfill(savepoint_session, apply=True)

    savepoint_session.refresh(material)
    assert material.color_options is None
    assert material.color_fragment is None
    assert _row_for(report, "EFAS-1") is None


def test_backfill_material_without_color_word_untouched(savepoint_session, make_test_material):
    make_test_material("MISC-1", "Generic Bracket 4in")

    report = run_backfill(savepoint_session, apply=True)

    assert _row_for(report, "MISC-1") is None


def test_backfill_is_idempotent_on_second_run(savepoint_session, make_test_material):
    material = make_test_material("GUTR-IDEMP", "End Cap (White/Bronze)")

    run_backfill(savepoint_session, apply=True)
    savepoint_session.refresh(material)
    first_options, first_fragment = material.color_options, material.color_fragment

    run_backfill(savepoint_session, apply=True)
    savepoint_session.refresh(material)

    assert material.color_options == first_options
    assert material.color_fragment == first_fragment


def test_backfill_skips_materials_already_backfilled(savepoint_session, make_test_material):
    """A material with color_options already set (from a prior run or from
    import) is not reprocessed — mirrors the embedding backfill's
    embedding IS NULL guard."""
    make_test_material(
        "GUTR-SKIP",
        "End Cap (White/Bronze)",
        color_options=["White", "Bronze"],
        color_fragment="(White/Bronze)",
    )

    report = run_backfill(savepoint_session, apply=True)

    assert _row_for(report, "GUTR-SKIP") is None
