"""GET /projects/{project_id}/price-comparison — ADR-0016.

Two sections per ProjectItem: `plan` (from active Price rows, independent of
any Order) and `supplier_responses` (from OrderItem rows on this project's
Orders, only for suppliers who were actually sent something). Both sections
are always present, even when empty (ADR-0016 §1) — this module never raises
for "no data", only for a missing project.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Order, OrderItem, Price, ProjectItem, Supplier


def _effective_price(item: OrderItem) -> float | None:
    """confirmed_price, else received_price, else quoted_price — ADR-0016 §4
    priority for comparing supplier_responses rows against each other."""
    if item.confirmed_price is not None:
        return float(item.confirmed_price)
    if item.received_price is not None:
        return float(item.received_price)
    return float(item.quoted_price)


def _latest_item_per_supplier(
    orders: list[Order], material_id: uuid.UUID
) -> dict[uuid.UUID, OrderItem]:
    """Among a project's Orders, for each supplier pick the OrderItem for
    material_id from the Order with the maximum created_at *among the Orders
    of that supplier that actually contain the material* — ADR-0016 §3.
    Orders not containing the material are skipped entirely for that
    supplier, not treated as "latest but empty"."""
    best_order_by_supplier: dict[uuid.UUID, Order] = {}
    for order in orders:
        has_material = any(oi.material_id == material_id for oi in order.items)
        if not has_material:
            continue
        current_best = best_order_by_supplier.get(order.supplier_id)
        if current_best is None or order.created_at > current_best.created_at:
            best_order_by_supplier[order.supplier_id] = order

    result: dict[uuid.UUID, OrderItem] = {}
    for supplier_id, order in best_order_by_supplier.items():
        result[supplier_id] = next(oi for oi in order.items if oi.material_id == material_id)
    return result


def get_price_comparison(db: Session, project_id: uuid.UUID) -> list[dict]:
    """Returns one row per ProjectItem: {project_item_id, material_id, plan,
    supplier_responses}. Caller is responsible for the project-existence
    404 (see app/api/project.py, same pattern as get_project())."""
    items = db.scalars(
        select(ProjectItem).where(ProjectItem.project_id == project_id)
    ).all()
    if not items:
        return []

    material_ids = {item.material_id for item in items}

    prices = db.scalars(
        select(Price).where(
            Price.material_id.in_(material_ids),
            Price.valid_to.is_(None),
        )
    ).all()
    prices_by_material: dict[uuid.UUID, list[Price]] = {}
    for price in prices:
        prices_by_material.setdefault(price.material_id, []).append(price)

    orders = db.scalars(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.project_id == project_id)
    ).all()

    supplier_ids: set[uuid.UUID] = {p.supplier_id for p in prices}
    for order in orders:
        supplier_ids.add(order.supplier_id)
    suppliers = db.scalars(select(Supplier).where(Supplier.id.in_(supplier_ids))).all()
    names_by_id = {s.id: s.name for s in suppliers}

    rows = []
    for item in items:
        material_prices = prices_by_material.get(item.material_id, [])
        plan = [
            {
                "supplier_id": p.supplier_id,
                "supplier_name": names_by_id[p.supplier_id],
                "price": float(p.price),
                "availability": p.availability,
            }
            for p in material_prices
        ]
        if plan:
            min_price = min(c["price"] for c in plan)
            for c in plan:
                c["is_cheapest"] = c["price"] == min_price

        latest_by_supplier = _latest_item_per_supplier(orders, item.material_id)
        supplier_responses = []
        for supplier_id, order_item in latest_by_supplier.items():
            supplier_responses.append(
                {
                    "supplier_id": supplier_id,
                    "supplier_name": names_by_id[supplier_id],
                    "quoted_price": float(order_item.quoted_price),
                    "received_price": (
                        float(order_item.received_price)
                        if order_item.received_price is not None
                        else None
                    ),
                    "confirmed_price": (
                        float(order_item.confirmed_price)
                        if order_item.confirmed_price is not None
                        else None
                    ),
                    "declined_at": order_item.declined_at,
                    "decline_reason": order_item.decline_reason,
                    "_effective_price": _effective_price(order_item),
                    "_declined": order_item.declined_at is not None,
                }
            )

        eligible = [r for r in supplier_responses if not r["_declined"]]
        if eligible:
            min_effective = min(r["_effective_price"] for r in eligible)
        else:
            min_effective = None
        for r in supplier_responses:
            r["is_cheapest"] = (
                not r["_declined"]
                and min_effective is not None
                and r["_effective_price"] == min_effective
            )
            del r["_effective_price"]
            del r["_declined"]

        rows.append(
            {
                "project_item_id": item.id,
                "material_id": item.material_id,
                "plan": plan,
                "supplier_responses": supplier_responses,
            }
        )

    return rows
