"""Оркестрация: project_id -> AllocationRun. Единственная точка, где solver.py
касается БД — сам solve_allocation() работает над чистыми dataclasses.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.allocation.preprocess import split_orphaned_materials
from app.allocation.solver import solve_allocation
from app.allocation.types import AllocationInput, MaterialInput, PriceInput, SupplierInput
from app.models import AllocationLine, AllocationRun, Price, ProjectItem, Supplier

ALGORITHM_VERSION = "adr-0002-v1"

_CENTS_PER_UNIT = 100


def _to_cents(amount) -> int:
    return round(float(amount) * _CENTS_PER_UNIT)


def _from_cents(cents: int) -> float:
    return cents / _CENTS_PER_UNIT


def run_allocation(db: Session, project_id: uuid.UUID) -> AllocationRun:
    project_items = db.scalars(
        select(ProjectItem).where(ProjectItem.project_id == project_id)
    ).all()

    materials = [
        MaterialInput(material_id=str(item.material_id), quantity=item.quantity)
        for item in project_items
    ]
    material_ids = {item.material_id for item in project_items}

    prices = db.scalars(
        select(Price).where(Price.material_id.in_(material_ids), Price.valid_to.is_(None))
    ).all()

    price_inputs = [
        PriceInput(
            material_id=str(price.material_id),
            supplier_id=str(price.supplier_id),
            unit_price_cents=_to_cents(price.price),
            availability=price.availability,
        )
        for price in prices
    ]

    solvable_materials, orphaned = split_orphaned_materials(materials, price_inputs)

    supplier_ids = {p.supplier_id for p in prices}
    suppliers = db.scalars(select(Supplier).where(Supplier.id.in_(supplier_ids))).all()
    supplier_inputs = [
        SupplierInput(
            supplier_id=str(supplier.id),
            flat_fee_cents=_to_cents(supplier.delivery_policy.get("flat_fee", 0)),
            free_shipping_threshold_cents=_to_cents(
                supplier.delivery_policy.get("free_shipping_threshold", 0)
            ),
            per_order_min_amount_cents=_to_cents(
                supplier.delivery_policy.get("per_order_min_amount", 0)
            ),
        )
        for supplier in suppliers
    ]

    result = solve_allocation(
        AllocationInput(
            materials=solvable_materials, suppliers=supplier_inputs, prices=price_inputs
        )
    )

    run = AllocationRun(
        project_id=project_id,
        algorithm_version=ALGORITHM_VERSION,
        orphaned_materials=[asdict(o) for o in orphaned],
    )
    db.add(run)
    db.flush()

    for line in result.lines:
        db.add(
            AllocationLine(
                allocation_run_id=run.id,
                material_id=uuid.UUID(line.material_id),
                supplier_id=uuid.UUID(line.supplier_id),
                quantity=line.quantity,
                unit_price=_from_cents(line.unit_price_cents),
                line_total=_from_cents(line.line_total_cents),
            )
        )

    db.commit()
    db.refresh(run)
    return run
