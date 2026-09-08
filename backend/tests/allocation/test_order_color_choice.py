"""create_orders_for_run blocks when the plan includes a material with
color_options and Project.color_choice is NULL — see ADR-0031 п.3."""

import pytest

from app.allocation.order_service import (
    ProjectColorChoiceRequiredError,
    create_orders_for_run,
)
from app.allocation.service import run_allocation


def test_create_orders_blocked_when_color_choice_missing(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material(sku="GUTR-COLOR")
    material.canonical_name = "End Cap (White/Bronze)"
    material.color_options = ["White", "Bronze"]
    material.color_fragment = "(White/Bronze)"
    session.commit()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    assert project.color_choice is None

    run = run_allocation(session, project.id)

    with pytest.raises(ProjectColorChoiceRequiredError):
        create_orders_for_run(session, project.id, run.id)


def test_create_orders_succeeds_when_color_choice_set(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material(sku="GUTR-COLOR2")
    material.canonical_name = "End Cap (White/Bronze)"
    material.color_options = ["White", "Bronze"]
    material.color_fragment = "(White/Bronze)"
    session.commit()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    project.color_choice = "White"
    session.commit()

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)

    assert len(orders) == 1


def test_create_orders_unaffected_for_projects_without_color_options(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Regression: projects whose materials never have color_options must
    keep working exactly as before — no new prompt, no new error."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material(sku="PLAIN-1")
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    assert project.color_choice is None

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)

    assert len(orders) == 1
