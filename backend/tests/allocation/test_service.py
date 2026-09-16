import pytest

from app.allocation.service import (
    EmptyProjectError,
    override_allocation_line_supplier,
    run_allocation,
)
from app.models import AllocationLine, AllocationRun, Project, Supplier


def test_run_allocation_persists_run_and_lines(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)

    assert isinstance(run, AllocationRun)
    assert run.project_id == project.id
    assert run.status == "ok"
    assert run.orphaned_materials == []

    persisted = session.get(AllocationRun, run.id)
    assert persisted is not None

    lines = session.query(AllocationLine).filter_by(allocation_run_id=run.id).all()
    assert len(lines) == 1
    assert lines[0].material_id == material.id
    assert lines[0].supplier_id == supplier.id
    assert lines[0].quantity == 10
    assert float(lines[0].unit_price) == 5.00
    assert float(lines[0].line_total) == 50.00


def test_run_allocation_records_orphaned_material_not_a_line(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    solvable_material = make_material()
    orphaned_material = make_material()
    make_price(solvable_material, supplier, price=5.00, availability=10)
    make_price(orphaned_material, supplier, price=3.00, availability=2)  # short by 8
    project = make_project([(solvable_material, 10), (orphaned_material, 10)])

    run = run_allocation(session, project.id)

    assert len(run.orphaned_materials) == 1
    orphaned_entry = run.orphaned_materials[0]
    assert orphaned_entry["material_id"] == str(orphaned_material.id)
    assert orphaned_entry["required_quantity"] == 10
    assert orphaned_entry["best_partial_supplier_id"] == str(supplier.id)
    assert orphaned_entry["best_partial_available"] == 2

    lines = session.query(AllocationLine).filter_by(allocation_run_id=run.id).all()
    assert len(lines) == 1
    assert lines[0].material_id == solvable_material.id


def test_run_allocation_skips_supplier_below_min_order_amount_for_single_item(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    cheap_but_gated = make_supplier(
        name="Gated Supplier", flat_fee=0.0, free_shipping_threshold=0.0, per_order_min_amount=100.0
    )
    fallback = make_supplier(name="Fallback Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, cheap_but_gated, price=1.00, availability=10)
    make_price(material, fallback, price=2.00, availability=10)
    project = make_project([(material, 1)])

    run = run_allocation(session, project.id)

    lines = session.query(AllocationLine).filter_by(allocation_run_id=run.id).all()
    assert len(lines) == 1
    assert lines[0].supplier_id == fallback.id


def test_run_allocation_records_supplier_summary_with_delivery_fee(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(
        flat_fee=10.0, free_shipping_threshold=1000.0, per_order_min_amount=0.0
    )
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 1)])

    run = run_allocation(session, project.id)

    assert len(run.supplier_summaries) == 1
    summary = run.supplier_summaries[0]
    assert summary["supplier_id"] == str(supplier.id)
    assert summary["goods_total"] == 5.00
    assert summary["delivery_fee"] == 10.00
    assert summary["free_shipping_achieved"] is False


def test_run_allocation_records_supplier_summary_with_tax_amount(
    db_session, make_supplier, make_material, make_price, make_project
):
    """ADR-0029 §5а: SupplierAllocationSummaryOut carries tax_amount (7% of
    goods_total, never delivery_fee) and total_with_tax (goods + tax +
    delivery)."""
    session, *_ = db_session
    supplier = make_supplier(
        flat_fee=10.0, free_shipping_threshold=1000.0, per_order_min_amount=0.0
    )
    material = make_material()
    make_price(material, supplier, price=100.00, availability=10)
    project = make_project([(material, 1)])

    run = run_allocation(session, project.id)

    summary = run.supplier_summaries[0]
    assert summary["goods_total"] == 100.00
    assert summary["delivery_fee"] == 10.00
    assert summary["tax_amount"] == 7.00
    assert summary["total_with_tax"] == 117.00


def test_run_allocation_records_supplier_summary_with_free_shipping(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(
        flat_fee=10.0, free_shipping_threshold=5.00, per_order_min_amount=0.0
    )
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 1)])

    run = run_allocation(session, project.id)

    summary = run.supplier_summaries[0]
    assert summary["goods_total"] == 5.00
    assert summary["delivery_fee"] == 0.0
    assert summary["free_shipping_achieved"] is True


def test_run_allocation_never_grants_free_shipping_when_threshold_unset(
    db_session, make_material, make_price, make_project
):
    """delivery_policy без ключа free_shipping_threshold (а не 0) не должен
    трактоваться солвером как 'бесплатная доставка всегда' — см. фикс
    различения 'порог не задан' vs 'порог явно 0' в service.py/solver.py."""
    session, project_ids, material_ids, supplier_ids, *_ = db_session
    supplier = Supplier(
        name="No Threshold Supplier",
        currency="USD",
        delivery_policy={"flat_fee": 10.0},
    )
    session.add(supplier)
    session.flush()
    supplier_ids.append(supplier.id)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 1)])

    run = run_allocation(session, project.id)

    summary = run.supplier_summaries[0]
    assert summary["delivery_fee"] == 10.00
    assert summary["free_shipping_achieved"] is False


def test_run_allocation_raises_on_project_with_no_items(db_session):
    session, project_ids, *_ = db_session
    project = Project(title="Empty Project", status="draft")
    session.add(project)
    session.flush()
    project_ids.append(project.id)

    with pytest.raises(EmptyProjectError):
        run_allocation(session, project.id)


def test_run_allocation_marks_infeasible_when_sole_supplier_misses_min_order_amount(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Regression for the reproduced bug (ADR-0003): a material with exactly
    one available-and-priced supplier, whose per_order_min_amount is not met
    by this order in isolation, makes the whole CP-SAT model infeasible
    (Constraint 1 forces x[m][s]=1 for the only candidate pair, Constraint 4
    then requires y[s]=0). Pre-fix, run_allocation() silently persisted an
    empty-but-"successful" AllocationRun instead of surfacing this."""
    session, *_ = db_session
    supplier = make_supplier(
        name="Gated Sole Supplier",
        flat_fee=0.0,
        free_shipping_threshold=0.0,
        per_order_min_amount=200.0,
    )
    material = make_material()
    make_price(material, supplier, price=13.25, availability=500)
    project = make_project([(material, 10)])  # 13.25 * 10 = 132.50, below the $200 minimum

    run = run_allocation(session, project.id)

    assert run.status == "infeasible"
    assert run.lines == []
    assert run.supplier_summaries == []


def test_run_allocation_leaves_split_categories_empty_when_category_unified(
    db_session, make_supplier, make_material, make_category, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    doors = make_category(name="TestDoors", requires_single_supplier=True)
    door1 = make_material(category=doors)
    door2 = make_material(category=doors)
    make_price(door1, supplier, price=5.00, availability=10)
    make_price(door2, supplier, price=6.00, availability=10)
    project = make_project([(door1, 1), (door2, 1)])

    run = run_allocation(session, project.id)

    assert run.status == "ok"
    assert run.split_categories == []


def test_run_allocation_reports_split_categories_when_category_actually_split(
    db_session, make_supplier, make_material, make_category, make_price, make_project
):
    """ADR-0028 §4: AllocationRun.split_categories lists a strict category
    only when the solver's actual chosen lines land on more than one distinct
    supplier -- computed after run_allocation, same point as supplier_summaries."""
    session, *_ = db_session
    s1 = make_supplier(name="Supplier One", flat_fee=0.0, free_shipping_threshold=0.0)
    s2 = make_supplier(name="Supplier Two", flat_fee=0.0, free_shipping_threshold=0.0)
    mesh = make_category(name="TestMesh", requires_single_supplier=True)
    mesh1 = make_material(category=mesh)
    mesh2 = make_material(category=mesh)
    # No common supplier for both -- forces a split (mirrors the ADR's
    # empirical Mesh catalog-coverage gap).
    make_price(mesh1, s1, price=5.00, availability=10)
    make_price(mesh2, s2, price=6.00, availability=10)
    project = make_project([(mesh1, 1), (mesh2, 1)])

    run = run_allocation(session, project.id)

    assert run.status == "ok"
    assert run.split_categories == ["TestMesh"]


def test_run_allocation_marks_infeasible_when_no_solvable_materials(
    db_session, make_supplier, make_material, make_price, make_project
):
    """NO_SOLVABLE_MATERIALS (every item orphaned by preprocessing) is the
    same "silently empty success" bug class as ILP infeasibility — both must
    surface as status == "infeasible", not just orphaned_materials without a
    persisted signal. See ADR-0003."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=3.00, availability=2)  # short by 8
    project = make_project([(material, 10)])

    run = run_allocation(session, project.id)

    assert run.status == "infeasible"
    assert run.lines == []
    assert run.supplier_summaries == []
    assert len(run.orphaned_materials) == 1
    assert run.orphaned_materials[0]["material_id"] == str(material.id)


def test_compute_split_categories_matches_solver_requires_single_supplier(
    db_session, make_supplier, make_material, make_category, make_price, make_project
):
    """ADR-0034 §3.1: both call sites (solver.py's materials_by_category and
    service.py's _compute_split_categories) must read
    Category.requires_single_supplier the same way. A category with the flag
    True and materials split across suppliers (via override) must produce a
    non-empty split_categories; a category with the flag False in the same
    shape must not."""
    session, *_ = db_session
    s1 = make_supplier(name="S1", flat_fee=0.0, free_shipping_threshold=0.0)
    s2 = make_supplier(name="S2", flat_fee=0.0, free_shipping_threshold=0.0)

    strict_cat = make_category(name="StrictCat", requires_single_supplier=True)
    strict_1 = make_material(category=strict_cat)
    strict_2 = make_material(category=strict_cat)
    make_price(strict_1, s1, price=5.00, availability=10)
    make_price(strict_2, s1, price=6.00, availability=10)
    make_price(strict_1, s2, price=7.00, availability=10)
    strict_project = make_project([(strict_1, 1), (strict_2, 1)])

    strict_run = run_allocation(session, strict_project.id)
    strict_line = (
        session.query(AllocationLine)
        .filter_by(allocation_run_id=strict_run.id, material_id=strict_1.id)
        .one()
    )
    override_allocation_line_supplier(session, strict_run.id, strict_line.id, s2.id)
    session.refresh(strict_run)
    assert strict_run.split_categories == ["StrictCat"]

    lax_cat = make_category(name="LaxCat", requires_single_supplier=False)
    lax_1 = make_material(category=lax_cat)
    lax_2 = make_material(category=lax_cat)
    make_price(lax_1, s1, price=5.00, availability=10)
    make_price(lax_2, s1, price=6.00, availability=10)
    make_price(lax_1, s2, price=7.00, availability=10)
    lax_project = make_project([(lax_1, 1), (lax_2, 1)])

    lax_run = run_allocation(session, lax_project.id)
    lax_line = (
        session.query(AllocationLine)
        .filter_by(allocation_run_id=lax_run.id, material_id=lax_1.id)
        .one()
    )
    override_allocation_line_supplier(session, lax_run.id, lax_line.id, s2.id)
    session.refresh(lax_run)
    assert lax_run.split_categories == []
