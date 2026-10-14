"""Tests for clear_min_order_qty.py -- see ADR-0045 §План выкатки п.3.

Most tests here run against the real configured DB (SessionLocal), same
constraint as test_audit_min_order_qty.py -- no sqlite/mocked-session path
exists in this codebase. test_still_set_rollback_path_calls_rollback_not_commit
is the one exception: it uses a hand-built fake session object instead of a
real one, specifically to prove the rollback/no-commit control flow fires
on a failed verification, without depending on being able to reproduce that
failure against a real identity map (which, after the fix, should never
actually happen with a real session -- that's the point of the fix).
"""

import datetime
import uuid

import pytest

from app.models.price import Price
from app.scripts.clear_min_order_qty import _load_targets, main


def _run_main(monkeypatch, db_session, price_ids, confirm):
    # clear_min_order_qty.main() opens its own SessionLocal() (it is a
    # standalone script, not a FastAPI route -- app.dependency_overrides
    # only patches get_db for route handlers) -- it cannot see rows the
    # fixture session has only flushed, not committed, so fixture data must
    # be committed first for the script's separate session/connection to
    # read it.
    session, *_ = db_session
    session.commit()

    argv = ["clear_min_order_qty.py"]
    for pid in price_ids:
        argv += ["--price-id", str(pid)]
    if confirm:
        argv.append("--confirm")
    monkeypatch.setattr("sys.argv", argv)
    main()


def _read_min_order_qty(price_id):
    # A fresh SessionLocal(), not the fixture's session -- main() commits
    # through its own separate session/connection, and this reads that
    # committed state back the same way a real operator re-checking the
    # database afterward would, rather than relying on the fixture
    # session's transaction isolation semantics.
    from app.core.database import SessionLocal

    fresh = SessionLocal()
    try:
        return fresh.get(Price, price_id).min_order_qty
    finally:
        fresh.close()


def test_dry_run_does_not_write(monkeypatch, db_session, make_material, make_supplier, make_price):
    material = make_material()
    supplier = make_supplier()
    price = make_price(material, supplier, min_order_qty=100)

    _run_main(monkeypatch, db_session, [price.id], confirm=False)

    assert _read_min_order_qty(price.id) == 100


def test_confirm_clears_only_the_given_ids(
    monkeypatch, db_session, make_material, make_supplier, make_price
):
    material = make_material()
    supplier = make_supplier()
    target = make_price(material, supplier, min_order_qty=100)
    other_supplier = make_supplier()
    untouched = make_price(make_material(), other_supplier, min_order_qty=50)

    _run_main(monkeypatch, db_session, [target.id], confirm=True)

    assert _read_min_order_qty(target.id) is None
    assert _read_min_order_qty(untouched.id) == 50


def test_unknown_id_refuses_without_writing(
    monkeypatch, db_session, make_material, make_supplier, make_price
):
    material = make_material()
    supplier = make_supplier()
    price = make_price(material, supplier, min_order_qty=100)
    unknown_id = uuid.uuid4()

    with pytest.raises(SystemExit):
        _run_main(monkeypatch, db_session, [price.id, unknown_id], confirm=True)

    assert _read_min_order_qty(price.id) == 100


def test_closed_price_id_refuses_without_writing(
    monkeypatch, db_session, make_material, make_supplier, make_price
):
    material = make_material()
    supplier = make_supplier()
    closed = make_price(
        material,
        supplier,
        min_order_qty=100,
        valid_to=datetime.date.today(),
    )

    with pytest.raises(SystemExit):
        _run_main(monkeypatch, db_session, [closed.id], confirm=True)

    assert _read_min_order_qty(closed.id) == 100


def test_already_null_id_refuses(monkeypatch, db_session, make_material, make_supplier, make_price):
    material = make_material()
    supplier = make_supplier()
    price = make_price(material, supplier, min_order_qty=None)

    with pytest.raises(SystemExit):
        _run_main(monkeypatch, db_session, [price.id], confirm=True)


def test_failed_verification_leaves_db_unchanged(
    monkeypatch, db_session, make_material, make_supplier, make_price
):
    """Real DB, real session, real UPDATE -- only the verification read
    (_verify_cleared) is monkeypatched to falsely report both ids as still
    non-null, so main() takes the rollback branch. Confirms end-to-end that
    when verification fails, nothing committed earlier in the same
    transaction survives -- read back with a completely separate, fresh
    SessionLocal() afterward, the same way an operator re-checking the
    database would, not through the fixture's own session/identity map."""
    from app.scripts import clear_min_order_qty

    material = make_material()
    supplier_a = make_supplier()
    supplier_b = make_supplier()
    price_a = make_price(material, supplier_a, min_order_qty=100)
    price_b = make_price(make_material(), supplier_b, min_order_qty=200)

    db_session[0].commit()

    original_verify = clear_min_order_qty._verify_cleared

    def _lying_verify(session, price_ids):
        # Real read happens via original_verify (so flush() is exercised
        # for real), then the reported values are overwritten to pretend
        # the UPDATE didn't take, forcing main() into its rollback branch.
        real_rows = original_verify(session, price_ids)
        return [(pid, 999) for pid, _moq in real_rows]

    monkeypatch.setattr(clear_min_order_qty, "_verify_cleared", _lying_verify)
    monkeypatch.setattr(
        "sys.argv",
        [
            "clear_min_order_qty.py",
            "--price-id",
            str(price_a.id),
            "--price-id",
            str(price_b.id),
            "--confirm",
        ],
    )

    with pytest.raises(SystemExit):
        clear_min_order_qty.main()

    assert _read_min_order_qty(price_a.id) == 100
    assert _read_min_order_qty(price_b.id) == 200


def test_mixed_valid_and_closed_ids_refuse_whole_batch(
    monkeypatch, db_session, make_material, make_supplier, make_price
):
    material = make_material()
    supplier_a = make_supplier()
    supplier_b = make_supplier()
    active = make_price(material, supplier_a, min_order_qty=100)
    closed = make_price(
        make_material(), supplier_b, min_order_qty=200, valid_to=datetime.date.today()
    )

    with pytest.raises(SystemExit):
        _run_main(monkeypatch, db_session, [active.id, closed.id], confirm=True)

    assert _read_min_order_qty(active.id) == 100
    assert _read_min_order_qty(closed.id) == 200


def test_load_targets_raises_on_missing_id(db_session, make_material, make_supplier, make_price):
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()
    price = make_price(material, supplier, min_order_qty=100)

    with pytest.raises(SystemExit):
        _load_targets(session, [price.id, uuid.uuid4()])


class _FakeColumnResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Not a real DB session -- this test exists specifically to prove the
    rollback/no-commit control flow in main() fires when the verification
    SELECT finds a non-null value, independent of whether a real session's
    identity map could ever actually produce that result (the whole point
    of selecting bare columns instead of ORM objects is that it shouldn't).
    """

    def __init__(self, target_price):
        self._target = target_price
        # Snapshotted independently of target_price's own attribute, which
        # main() mutates in place (row.min_order_qty = None) -- reading
        # self._target.min_order_qty directly here would follow that same
        # mutation and could never actually simulate "still non-null",
        # which defeats the purpose of this test.
        self._verify_value = target_price.min_order_qty
        self.rolled_back = False
        self.committed = False
        self.flushed = False

    def scalars(self, _stmt):
        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        return _Result([self._target])

    def execute(self, _stmt):
        # Simulate a verification SELECT that (incorrectly, for this test)
        # still finds the old value -- proves main() reacts to that, not
        # that this can happen with a real session post-fix.
        return _FakeColumnResult([(self._target.id, self._verify_value)])

    def get(self, model, obj_id):
        # _print_preview looks up Material.canonical_name/internal_sku and
        # Supplier.name for display purposes only -- any object with those
        # attributes satisfies it, this isn't exercising real lookup logic.
        class _Stub:
            name = "stub-supplier"
            canonical_name = "stub-material"
            internal_sku = "STUB-SKU"

        return _Stub()

    def flush(self):
        self.flushed = True

    def rollback(self):
        self.rolled_back = True

    def commit(self):
        self.committed = True

    def close(self):
        pass


def test_still_set_rollback_path_calls_rollback_not_commit(monkeypatch):
    from app.scripts import clear_min_order_qty

    fake_price = Price(
        id=uuid.uuid4(),
        material_id=uuid.uuid4(),
        supplier_id=uuid.uuid4(),
        price=10.0,
        currency="USD",
        availability=None,
        min_order_qty=100,  # still non-null -- verification should catch this
        valid_from=datetime.date.today(),
        valid_to=None,
    )
    fake_session = _FakeSession(fake_price)
    monkeypatch.setattr(clear_min_order_qty, "SessionLocal", lambda: fake_session)
    monkeypatch.setattr(
        "sys.argv", ["clear_min_order_qty.py", "--price-id", str(fake_price.id), "--confirm"]
    )

    with pytest.raises(SystemExit):
        clear_min_order_qty.main()

    assert fake_session.rolled_back is True
    assert fake_session.committed is False
