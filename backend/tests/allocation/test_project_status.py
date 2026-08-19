from app.allocation.order_service import create_orders_for_run
from app.allocation.service import run_allocation


def test_run_allocation_moves_draft_to_calculated_on_solved_run(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    assert project.status == "draft"

    run_allocation(session, project.id)

    session.refresh(project)
    assert project.status == "calculated"


def test_run_allocation_infeasible_run_does_not_move_draft_project(
    db_session, make_supplier, make_material, make_price, make_project
):
    """A supplier under its own per_order_min_amount for a single line makes
    the model infeasible (ADR-0002 Constraint 4 vs Constraint 1) — the
    project must stay draft, not silently advance. See ADR-0011 п.2."""
    session, *_ = db_session
    supplier = make_supplier(
        flat_fee=0.0, free_shipping_threshold=0.0, per_order_min_amount=1000.0
    )
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])  # 10 * 5.00 = 50.00, far under 1000.00

    run = run_allocation(session, project.id)

    assert run.status == "infeasible"
    session.refresh(project)
    assert project.status == "draft"


def test_run_allocation_infeasible_run_does_not_regress_calculated_project(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Starts from a project with one successful run (status=calculated),
    then expires its only workable price and replaces it with one that
    violates per_order_min_amount, forcing the second run to be infeasible
    (orphaned materials alone don't make a whole run infeasible — only a
    min-order violation or an empty solvable set does, see
    docs/decisions/0003-infeasible-allocation-status.md). The project must
    stay at "calculated", not regress to "draft"."""
    session, *_ = db_session
    ok_supplier = make_supplier(
        name="OK Supplier", flat_fee=0.0, free_shipping_threshold=0.0
    )
    material = make_material()
    make_price(material, ok_supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run_allocation(session, project.id)
    session.refresh(project)
    assert project.status == "calculated"

    # Expire the only workable price and replace it with one that violates
    # per_order_min_amount, so the next run is infeasible.
    import datetime

    from app.models import Price

    session.query(Price).filter(
        Price.material_id == material.id, Price.supplier_id == ok_supplier.id
    ).update({"valid_to": datetime.date.today()})
    session.flush()
    high_min_supplier = make_supplier(
        name="High Min Supplier",
        flat_fee=0.0,
        free_shipping_threshold=0.0,
        per_order_min_amount=1000.0,
    )
    make_price(material, high_min_supplier, price=5.00, availability=10)

    run = run_allocation(session, project.id)

    assert run.status == "infeasible"
    session.refresh(project)
    assert project.status == "calculated"  # unchanged, not regressed to draft


def test_create_orders_moves_calculated_to_ordered(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    session.refresh(project)
    assert project.status == "calculated"

    create_orders_for_run(session, project.id, run.id)

    session.refresh(project)
    assert project.status == "ordered"


def test_recalculating_ordered_project_rolls_back_to_calculated(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    first_run = run_allocation(session, project.id)
    create_orders_for_run(session, project.id, first_run.id)
    session.refresh(project)
    assert project.status == "ordered"

    run_allocation(session, project.id)

    session.refresh(project)
    assert project.status == "calculated"
