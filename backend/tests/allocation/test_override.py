"""Tests for manual supplier override on a single AllocationLine — ADR-0006.

Covers: recalculation of both affected suppliers' summaries (goods_total,
free_shipping_achieved, delivery_fee, below_min_order), validation of the
new (material, supplier) pair, and persistence of the override fields.
"""

import uuid

import pytest

from app.allocation.service import (
    InvalidOverrideSupplierError,
    LineNotFoundError,
    override_allocation_line_supplier,
    run_allocation,
)
from app.models import AllocationLine


def test_override_moves_line_and_updates_original_fields(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    old_supplier = make_supplier(name="Old Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    new_supplier = make_supplier(name="New Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, old_supplier, price=5.00, availability=10)
    make_price(material, new_supplier, price=7.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()
    assert line.supplier_id == old_supplier.id  # sanity: cheaper supplier picked

    updated = override_allocation_line_supplier(session, run.id, line.id, new_supplier.id)

    assert updated.supplier_id == new_supplier.id
    assert float(updated.unit_price) == 7.00
    assert float(updated.line_total) == 70.00
    assert updated.overridden_at is not None
    assert updated.original_supplier_id == old_supplier.id
    assert float(updated.original_unit_price) == 5.00


def test_second_override_does_not_overwrite_original_fields(
    db_session, make_supplier, make_material, make_price, make_project
):
    """original_* must always point at the ILP result, not at the previous
    override — otherwise the "not cheapest" comparison loses its baseline
    after a second override of the same line. See ADR-0006 п.1."""
    session, *_ = db_session
    original_supplier = make_supplier(
        name="Original Supplier", flat_fee=0.0, free_shipping_threshold=0.0
    )
    second_supplier = make_supplier(
        name="Second Supplier", flat_fee=0.0, free_shipping_threshold=0.0
    )
    third_supplier = make_supplier(name="Third Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, original_supplier, price=5.00, availability=10)
    make_price(material, second_supplier, price=7.00, availability=10)
    make_price(material, third_supplier, price=9.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()

    override_allocation_line_supplier(session, run.id, line.id, second_supplier.id)
    updated = override_allocation_line_supplier(session, run.id, line.id, third_supplier.id)

    assert updated.supplier_id == third_supplier.id
    assert updated.original_supplier_id == original_supplier.id
    assert float(updated.original_unit_price) == 5.00


def test_override_rejects_supplier_without_active_price(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    old_supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    supplier_without_price = make_supplier(
        name="No Price Supplier", flat_fee=0.0, free_shipping_threshold=0.0
    )
    material = make_material()
    make_price(material, old_supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()

    with pytest.raises(InvalidOverrideSupplierError):
        override_allocation_line_supplier(session, run.id, line.id, supplier_without_price.id)


def test_override_allowed_despite_insufficient_availability(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Manual override may proceed even when the new supplier's Price.availability
    is explicitly less than the required quantity — the user may have out-of-band
    context the solver doesn't. See ADR-0006 п.2."""
    session, *_ = db_session
    old_supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    short_supplier = make_supplier(name="Short Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, old_supplier, price=5.00, availability=10)
    make_price(material, short_supplier, price=6.00, availability=2)  # short by 8
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()

    updated = override_allocation_line_supplier(session, run.id, line.id, short_supplier.id)

    assert updated.supplier_id == short_supplier.id


def test_override_raises_for_unknown_line(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)

    with pytest.raises(LineNotFoundError):
        override_allocation_line_supplier(session, run.id, uuid.uuid4(), supplier.id)


def test_override_breaks_free_shipping_for_old_supplier(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Moving the only line that was keeping the old supplier's order over
    the free-shipping threshold must flip free_shipping_achieved back to
    False and reinstate flat_fee. See ADR-0006 п.4."""
    session, *_ = db_session
    old_supplier = make_supplier(
        name="Old Supplier", flat_fee=10.0, free_shipping_threshold=40.0
    )
    new_supplier = make_supplier(
        name="New Supplier", flat_fee=15.0, free_shipping_threshold=1000.0
    )
    material = make_material()
    # old_supplier's only line is exactly what clears its $40 threshold.
    make_price(material, old_supplier, price=5.00, availability=10)
    make_price(material, new_supplier, price=6.00, availability=10)
    project = make_project([(material, 10)])  # goods_total = 50.00 >= 40.00

    run = run_allocation(session, project.id)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()
    pre_summary = {s["supplier_id"]: s for s in run.supplier_summaries}
    assert pre_summary[str(old_supplier.id)]["free_shipping_achieved"] is True
    assert pre_summary[str(old_supplier.id)]["delivery_fee"] == 0.0

    override_allocation_line_supplier(session, run.id, line.id, new_supplier.id)
    session.refresh(run)

    summaries = {s["supplier_id"]: s for s in run.supplier_summaries}
    # old_supplier now has zero lines -> summary removed entirely.
    assert str(old_supplier.id) not in summaries

    new_summary = summaries[str(new_supplier.id)]
    assert new_summary["goods_total"] == 60.00
    assert new_summary["free_shipping_achieved"] is False
    assert new_summary["delivery_fee"] == 15.00


def test_override_achieves_free_shipping_for_new_supplier(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Symmetric case: moving a line onto a supplier who already has other
    lines can push their order total over threshold, flipping
    free_shipping_achieved to True and delivery_fee to 0. See ADR-0006 п.4."""
    session, *_ = db_session
    old_supplier = make_supplier(
        name="Old Supplier", flat_fee=0.0, free_shipping_threshold=0.0
    )
    new_supplier = make_supplier(
        name="New Supplier", flat_fee=20.0, free_shipping_threshold=46.0
    )
    moving_material = make_material()
    staying_material = make_material()
    # moving_material is deliberately much pricier at new_supplier than at
    # old_supplier, so the ILP never has a consolidation incentive to place
    # it there on its own merit — the only way it ends up at new_supplier is
    # via a manual override.
    make_price(moving_material, old_supplier, price=5.00, availability=10)
    make_price(moving_material, new_supplier, price=30.00, availability=10)
    make_price(staying_material, new_supplier, price=40.00, availability=10)
    project = make_project([(moving_material, 1), (staying_material, 1)])

    run = run_allocation(session, project.id)
    moving_line = (
        session.query(AllocationLine)
        .filter_by(allocation_run_id=run.id, material_id=moving_material.id)
        .one()
    )
    assert moving_line.supplier_id == old_supplier.id  # sanity: ILP didn't consolidate
    pre_summary = {s["supplier_id"]: s for s in run.supplier_summaries}
    assert pre_summary[str(new_supplier.id)]["free_shipping_achieved"] is False

    override_allocation_line_supplier(session, run.id, moving_line.id, new_supplier.id)
    session.refresh(run)

    summaries = {s["supplier_id"]: s for s in run.supplier_summaries}
    new_summary = summaries[str(new_supplier.id)]
    assert new_summary["goods_total"] == 70.00  # 40.00 + 30.00
    assert new_summary["free_shipping_achieved"] is True
    assert new_summary["delivery_fee"] == 0.0


def test_override_flags_below_min_order_without_blocking(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Overriding a line onto a supplier gated by per_order_min_amount, where
    that single line alone doesn't meet the minimum, must not be blocked
    (unlike the hard ILP constraint) but must surface as below_min_order on
    the recomputed summary. See ADR-0006 п.4."""
    session, *_ = db_session
    old_supplier = make_supplier(
        name="Old Supplier", flat_fee=0.0, free_shipping_threshold=0.0
    )
    gated_supplier = make_supplier(
        name="Gated Supplier",
        flat_fee=0.0,
        free_shipping_threshold=0.0,
        per_order_min_amount=100.0,
    )
    material = make_material()
    make_price(material, old_supplier, price=5.00, availability=10)
    make_price(material, gated_supplier, price=6.00, availability=10)
    project = make_project([(material, 1)])

    run = run_allocation(session, project.id)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()
    assert line.supplier_id == old_supplier.id  # sanity: gated_supplier not engaged initially

    override_allocation_line_supplier(session, run.id, line.id, gated_supplier.id)
    session.refresh(run)

    summaries = {s["supplier_id"]: s for s in run.supplier_summaries}
    gated_summary = summaries[str(gated_supplier.id)]
    assert gated_summary["goods_total"] == 6.00  # well under the $100 minimum
    assert gated_summary["below_min_order"] is True


def test_override_clears_below_min_order_when_no_longer_applicable(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    other_supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    gated_supplier = make_supplier(
        name="Gated Supplier",
        flat_fee=0.0,
        free_shipping_threshold=0.0,
        per_order_min_amount=10.0,
    )
    material = make_material()
    make_price(material, other_supplier, price=5.00, availability=10)
    make_price(material, gated_supplier, price=20.00, availability=10)
    project = make_project([(material, 1)])

    run = run_allocation(session, project.id)
    line = session.query(AllocationLine).filter_by(allocation_run_id=run.id).one()

    override_allocation_line_supplier(session, run.id, line.id, gated_supplier.id)
    session.refresh(run)

    summaries = {s["supplier_id"]: s for s in run.supplier_summaries}
    assert summaries[str(gated_supplier.id)]["below_min_order"] is False
