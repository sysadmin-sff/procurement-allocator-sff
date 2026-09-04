"""Оркестрация: project_id -> AllocationRun. Единственная точка, где solver.py
касается БД — сам solve_allocation() работает над чистыми dataclasses.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.allocation.preprocess import split_orphaned_materials
from app.allocation.solver import STRICT_CATEGORIES, solve_allocation
from app.allocation.tax import calculate_tax
from app.allocation.types import AllocationInput, MaterialInput, PriceInput, SupplierInput
from app.models import (
    AllocationLine,
    AllocationRun,
    Material,
    Price,
    Project,
    ProjectItem,
    Supplier,
)

ALGORITHM_VERSION = "adr-0028-v1"
"""Модель ограничений изменилась под ADR-0028: новые diff[C][m]-переменные и
штраф за разброс поставщика внутри строгой категории (Doors/Gutter/Profil/
Mesh/Roof panels) добавлены в целевую функцию solve_allocation. Это меняет
саму постановку задачи, не только детали реализации — версия бампнута, как
и предвидела ADR-0002 "Последствия" ("если модель ограничений изменится...
это будет новый ADR и новая версия алгоритма"). Была "adr-0005-v1"."""

_CENTS_PER_UNIT = 100

_SOLVED_STATUSES = ("OPTIMAL", "FEASIBLE")
"""solve_allocation() statuses that mean 'a feasible assignment was found'.
Anything else — INFEASIBLE, MODEL_INVALID, UNKNOWN, NO_SOLVABLE_MATERIALS —
persists as AllocationRun.status == "infeasible" instead of a silent empty
"success". See ADR-0003."""


class EmptyProjectError(Exception):
    """Проект существует, но у него нет ни одной позиции (ProjectItem) —
    считать расчёт не над чем. Отдельно от "проекта не существует": то
    проверяет вызывающая сторона (например, API-роут через 404 до вызова
    run_allocation), это не забота солвера."""

    def __init__(self, project_id: uuid.UUID):
        self.project_id = project_id
        super().__init__(f"Project {project_id} has no items to allocate")


class LineNotFoundError(Exception):
    """AllocationLine с данным id не существует или не принадлежит указанному
    AllocationRun — тот же паттерн 404-guard, что уже есть у GET
    /allocations/{run_id} (route проверяет run.project_id, здесь service
    проверяет line.allocation_run_id). См. ADR-0006 п.5."""

    def __init__(self, run_id: uuid.UUID, line_id: uuid.UUID):
        self.run_id = run_id
        self.line_id = line_id
        super().__init__(f"AllocationLine {line_id} not found in AllocationRun {run_id}")


class InvalidOverrideSupplierError(Exception):
    """Новый поставщик не имеет актуальной Price (valid_to IS NULL) на
    материал строки — override физически не может посчитать unit_price.
    Availability не проверяется здесь: недостаточное наличие не блокирует
    ручное переопределение, см. ADR-0006 п.2."""

    def __init__(self, material_id: uuid.UUID, supplier_id: uuid.UUID):
        self.material_id = material_id
        self.supplier_id = supplier_id
        super().__init__(
            f"Supplier {supplier_id} has no active price for material {material_id}"
        )


def _to_cents(amount) -> int:
    return round(float(amount) * _CENTS_PER_UNIT)


def _from_cents(cents: int) -> float:
    return cents / _CENTS_PER_UNIT


def run_allocation(db: Session, project_id: uuid.UUID) -> AllocationRun:
    project_items = db.scalars(
        select(ProjectItem).where(ProjectItem.project_id == project_id)
    ).all()

    if not project_items:
        raise EmptyProjectError(project_id)

    materials = [
        MaterialInput(
            material_id=str(item.material_id),
            quantity=item.quantity,
            category=item.material.category,
        )
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
            free_shipping_threshold_cents=(
                None
                if supplier.delivery_policy.get("free_shipping_threshold") is None
                else _to_cents(supplier.delivery_policy["free_shipping_threshold"])
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

    solved = result.status in _SOLVED_STATUSES

    supplier_summaries = (
        [
            {
                "supplier_id": s.supplier_id,
                "goods_total": _from_cents(s.goods_total_cents),
                "delivery_fee": _from_cents(s.delivery_fee_cents),
                "tax_amount": _from_cents(calculate_tax(s.goods_total_cents)),
                "total_with_tax": _from_cents(
                    s.goods_total_cents + calculate_tax(s.goods_total_cents) + s.delivery_fee_cents
                ),
                "free_shipping_achieved": s.free_shipping_achieved,
                # Always False fresh out of the solver: ADR-0002 Constraint 4
                # (per_order_min_amount) is a hard ILP constraint, so a
                # solved run can never engage a supplier below their
                # minimum. Only a manual override (ADR-0006) can push a
                # supplier's remaining goods_total under it.
                "below_min_order": False,
            }
            for s in result.supplier_summaries
        ]
        if solved
        else []
    )

    run = AllocationRun(
        project_id=project_id,
        algorithm_version=ALGORITHM_VERSION,
        status="ok" if solved else "infeasible",
        orphaned_materials=[asdict(o) for o in orphaned],
        supplier_summaries=supplier_summaries,
    )
    db.add(run)
    db.flush()

    if solved:
        project = db.get(Project, project_id)
        if project.status in ("draft", "ordered"):
            project.status = "calculated"

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
        db.flush()
        run.split_categories = _compute_split_categories(db, run.id)

    db.commit()
    db.refresh(run)
    return run


def _compute_split_categories(db: Session, run_id: uuid.UUID) -> list[str]:
    """ADR-0028 §4: a strict category is "split" for this run if the project's
    current AllocationLine rows for that category (joined to Material.category)
    are assigned to more than one distinct supplier. Recomputed from scratch
    from the current line state -- same recompute point/style as
    _rebuild_supplier_summary (ADR-0006 §4), not an incremental patch."""
    rows = db.execute(
        select(Material.category, AllocationLine.supplier_id)
        .join(Material, Material.id == AllocationLine.material_id)
        .where(AllocationLine.allocation_run_id == run_id)
    ).all()

    suppliers_by_category: dict[str, set[uuid.UUID]] = {}
    for category, supplier_id in rows:
        if category not in STRICT_CATEGORIES:
            continue
        suppliers_by_category.setdefault(category, set()).add(supplier_id)

    return sorted(
        category
        for category, supplier_ids in suppliers_by_category.items()
        if len(supplier_ids) > 1
    )


def _rebuild_supplier_summary(
    db: Session, run_id: uuid.UUID, supplier_id: uuid.UUID
) -> dict | None:
    """Recompute one supplier's summary from the current AllocationLine rows
    of this run, from scratch (not an incremental patch) — see ADR-0006 п.4.
    Returns None if the supplier no longer has any lines in this run (the
    summary is dropped entirely, matching how a supplier with zero lines was
    never included by run_allocation() in the first place)."""
    lines = db.scalars(
        select(AllocationLine).where(
            AllocationLine.allocation_run_id == run_id,
            AllocationLine.supplier_id == supplier_id,
        )
    ).all()
    if not lines:
        return None

    supplier = db.get(Supplier, supplier_id)
    goods_total_cents = sum(_to_cents(line.line_total) for line in lines)

    free_shipping_threshold = supplier.delivery_policy.get("free_shipping_threshold")
    free_shipping_threshold_cents = (
        None if free_shipping_threshold is None else _to_cents(free_shipping_threshold)
    )
    free_shipping_achieved = (
        free_shipping_threshold_cents is not None
        and goods_total_cents >= free_shipping_threshold_cents
    )
    flat_fee_cents = _to_cents(supplier.delivery_policy.get("flat_fee", 0))
    delivery_fee_cents = 0 if free_shipping_achieved else flat_fee_cents

    per_order_min_amount_cents = _to_cents(supplier.delivery_policy.get("per_order_min_amount", 0))
    below_min_order = goods_total_cents < per_order_min_amount_cents

    tax_amount_cents = calculate_tax(goods_total_cents)

    return {
        "supplier_id": str(supplier_id),
        "goods_total": _from_cents(goods_total_cents),
        "delivery_fee": _from_cents(delivery_fee_cents),
        "tax_amount": _from_cents(tax_amount_cents),
        "total_with_tax": _from_cents(goods_total_cents + tax_amount_cents + delivery_fee_cents),
        "free_shipping_achieved": free_shipping_achieved,
        "below_min_order": below_min_order,
    }


def override_allocation_line_supplier(
    db: Session,
    run_id: uuid.UUID,
    line_id: uuid.UUID,
    new_supplier_id: uuid.UUID,
    source_order_item_id: uuid.UUID | None = None,
    overridden_by_user_id: uuid.UUID | None = None,
) -> AllocationLine:
    """Manually reassign one AllocationLine to a different supplier — ADR-0006.

    Persists the override on the line (original_supplier_id/original_unit_price
    are recorded only on the *first* override — see ADR-0006 п.1) and
    recomputes both affected suppliers' summaries on AllocationRun.
    Availability is intentionally not checked here: an explicit shortfall
    doesn't block a manual override, see ADR-0006 п.2. Money math stays on
    the backend per CLAUDE.md principle 4.

    source_order_item_id — see ADR-0014 п.3/п.5. Passed only by the
    find-replacement flow; every other caller (ordinary manual override on
    AllocationResultPage) omits it, and this always resets
    overridden_via_order_item_id to NULL — a later override must not keep
    attributing the line's current state to an unrelated prior decline.
    """
    line = db.get(AllocationLine, line_id)
    if line is None or line.allocation_run_id != run_id:
        raise LineNotFoundError(run_id, line_id)

    new_price = db.scalars(
        select(Price).where(
            Price.material_id == line.material_id,
            Price.supplier_id == new_supplier_id,
            Price.valid_to.is_(None),
        )
    ).first()
    if new_price is None:
        raise InvalidOverrideSupplierError(line.material_id, new_supplier_id)

    old_supplier_id = line.supplier_id

    if line.overridden_at is None:
        line.original_supplier_id = line.supplier_id
        line.original_unit_price = line.unit_price

    line.supplier_id = new_supplier_id
    line.unit_price = new_price.price
    line.line_total = float(new_price.price) * line.quantity
    line.overridden_at = datetime.now(timezone.utc)
    line.overridden_via_order_item_id = source_order_item_id
    line.overridden_by_user_id = overridden_by_user_id
    db.flush()

    run = db.get(AllocationRun, run_id)
    affected_supplier_ids = {str(old_supplier_id), str(new_supplier_id)}
    rebuilt = {
        str(supplier_id): _rebuild_supplier_summary(db, run_id, supplier_id)
        for supplier_id in (old_supplier_id, new_supplier_id)
    }

    updated_summaries = [
        s for s in run.supplier_summaries if s["supplier_id"] not in affected_supplier_ids
    ]
    for supplier_id_str in affected_supplier_ids:
        summary = rebuilt[supplier_id_str]
        if summary is not None:
            updated_summaries.append(summary)
    run.supplier_summaries = updated_summaries
    run.split_categories = _compute_split_categories(db, run_id)

    db.commit()
    db.refresh(line)
    return line
