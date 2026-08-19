"""Order creation from an AllocationRun, and confirmed-price entry on OrderItem
— see ADR-0007.

Order/OrderItem are snapshots, not live references: OrderItem copies
material_id/quantity/quoted_price by value at creation time, never joins back
through AllocationLine. AllocationLine.ordered_at marks "already ordered" but
does not block a later manual override (ADR-0006) — see ADR-0007 п.2.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AllocationLine, AllocationRun, Order, OrderItem, Project, Supplier

SIGNIFICANT_PRICE_DELTA_PCT = 10
"""Threshold above which a quoted vs. confirmed price discrepancy is flagged
as requiring attention on OrderDetailPage. Deliberately not the same as the
20% price-list review threshold (docs/spec.md §3) — see ADR-0007 п.4 for why
a lower, per-line, already-being-reviewed signal warrants a lower bar."""


class RunNotFoundError(Exception):
    """AllocationRun with the given id does not exist or does not belong to
    the given project — same 404-guard pattern as the rest of the allocation
    API. See ADR-0006 п.5 precedent."""

    def __init__(self, project_id: uuid.UUID, run_id: uuid.UUID):
        self.project_id = project_id
        self.run_id = run_id
        super().__init__(f"AllocationRun {run_id} not found in project {project_id}")


class OrderItemNotFoundError(Exception):
    def __init__(self, order_id: uuid.UUID, item_id: uuid.UUID):
        self.order_id = order_id
        self.item_id = item_id
        super().__init__(f"OrderItem {item_id} not found in Order {order_id}")


class DraftOrderConflictError(Exception):
    """Raised when create_orders_for_run() is called without replace_drafts
    while at least one supplier in the run's supplier_summaries already has
    a draft Order in this project from a prior run — see ADR-0012 п.1/п.2.

    suppliers_with_existing_drafts mirrors the 409 body shape exactly (list
    per supplier, list of existing_draft_orders per supplier — never a single
    object, real dev data has suppliers with more than one, see ADR-0012
    "Контекст") so the API layer can serialize it without recomputing.
    """

    def __init__(self, suppliers_with_existing_drafts: list[dict]):
        self.suppliers_with_existing_drafts = suppliers_with_existing_drafts
        super().__init__("Draft orders already exist for one or more suppliers in this run")


def _conflicting_draft_orders_by_supplier(
    db: Session, project_id: uuid.UUID, supplier_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[Order]]:
    """Existing draft Orders in this project for suppliers also present in
    the current run — approved/sent Orders never participate (ADR-0012 п.1)."""
    if not supplier_ids:
        return {}
    existing = db.scalars(
        select(Order)
        .options(selectinload(Order.items))
        .where(
            Order.project_id == project_id,
            Order.status == "draft",
            Order.supplier_id.in_(supplier_ids),
        )
    ).all()
    by_supplier: dict[uuid.UUID, list[Order]] = {}
    for order in existing:
        by_supplier.setdefault(order.supplier_id, []).append(order)
    return by_supplier


def _order_has_confirmed_prices(order: Order) -> bool:
    return any(item.confirmed_price is not None for item in order.items)


def _serialize_conflicts(
    db: Session, conflicts: dict[uuid.UUID, list[Order]]
) -> list[dict]:
    suppliers = db.scalars(
        select(Supplier).where(Supplier.id.in_(conflicts.keys()))
    ).all()
    names_by_id = {supplier.id: supplier.name for supplier in suppliers}

    result = []
    for supplier_id, orders in conflicts.items():
        result.append(
            {
                "supplier_id": supplier_id,
                "supplier_name": names_by_id[supplier_id],
                "existing_draft_orders": [
                    {
                        "order_id": order.id,
                        "total_amount": float(order.total_amount),
                        "has_confirmed_prices": _order_has_confirmed_prices(order),
                    }
                    for order in orders
                ],
            }
        )
    return result


def _delete_orders(db: Session, orders: list[Order]) -> None:
    """Explicit application-level cascade: order_items.order_id has no
    ON DELETE CASCADE (verified against the schema — see ADR-0009
    "Контекст"), so OrderItem rows must be deleted before their Order, same
    pattern as delete_project() in app/api/project.py. See ADR-0012 п.2."""
    order_ids = [order.id for order in orders]
    if not order_ids:
        return
    db.query(OrderItem).filter(OrderItem.order_id.in_(order_ids)).delete(
        synchronize_session=False
    )
    db.query(Order).filter(Order.id.in_(order_ids)).delete(synchronize_session=False)


def create_orders_for_run(
    db: Session, project_id: uuid.UUID, run_id: uuid.UUID, replace_drafts: bool = False
) -> list[Order]:
    """Create one Order per supplier in the run's current supplier_summaries
    (i.e. after any ADR-0006 overrides), snapshotting each supplier's current
    AllocationLine rows into OrderItem. Marks every line that went into an
    Order with ordered_at.

    Guards against accidental duplicate draft Orders — see ADR-0012. Before
    inserting, checks (per supplier in this run) whether a draft Order for
    that supplier already exists elsewhere in this project:
    - No conflicts, or replace_drafts=True: proceeds as before (ADR-0007
      п.2's "re-order is legitimate" is unchanged — this only gates the
      *default*, unconfirmed path, not re-ordering itself).
    - Conflicts and replace_drafts is not True: raises
      DraftOrderConflictError, creates and deletes nothing.
    - replace_drafts=True: deletes the conflicting suppliers' existing draft
      Order/OrderItem rows (application-level cascade, no DB-level
      ON DELETE CASCADE exists for order_items.order_id) before the normal
      creation logic runs, in the same transaction. Suppliers without a
      conflict (new in this run) are unaffected. approved/sent Orders are
      never conflicts and are never touched, at any replace_drafts value.
    """
    run = db.get(AllocationRun, run_id)
    if run is None or run.project_id != project_id:
        raise RunNotFoundError(project_id, run_id)

    supplier_ids = {uuid.UUID(summary["supplier_id"]) for summary in run.supplier_summaries}
    conflicts = _conflicting_draft_orders_by_supplier(db, project_id, supplier_ids)

    if conflicts:
        if not replace_drafts:
            raise DraftOrderConflictError(_serialize_conflicts(db, conflicts))
        _delete_orders(db, [order for orders in conflicts.values() for order in orders])
        db.flush()

    now = datetime.now(timezone.utc)
    orders: list[Order] = []

    for summary in run.supplier_summaries:
        supplier_id = uuid.UUID(summary["supplier_id"])
        lines = db.scalars(
            select(AllocationLine).where(
                AllocationLine.allocation_run_id == run_id,
                AllocationLine.supplier_id == supplier_id,
            )
        ).all()
        if not lines:
            continue

        order = Order(
            project_id=project_id,
            supplier_id=supplier_id,
            status="draft",
            total_amount=sum(float(line.line_total) for line in lines),
            delivery_fee=summary["delivery_fee"],
        )
        db.add(order)
        db.flush()

        for line in lines:
            db.add(
                OrderItem(
                    order_id=order.id,
                    material_id=line.material_id,
                    quantity=line.quantity,
                    quoted_price=line.unit_price,
                )
            )
            line.ordered_at = now

        orders.append(order)

    if orders:
        project = db.get(Project, project_id)
        project.status = "ordered"

    db.commit()
    for order in orders:
        db.refresh(order)
    return orders


def price_delta(
    quoted_price: float, confirmed_price: float | None
) -> tuple[float | None, float | None]:
    """(delta_abs, delta_pct) — both None if confirmed_price is None (no
    basis for comparison yet, not 0). See ADR-0007 п.1/п.4."""
    if confirmed_price is None:
        return None, None
    delta = float(confirmed_price) - float(quoted_price)
    delta_pct = (delta / float(quoted_price) * 100) if float(quoted_price) != 0 else 0.0
    return delta, delta_pct


def set_confirmed_price(
    db: Session, order_id: uuid.UUID, item_id: uuid.UUID, confirmed_price: float | None
) -> OrderItem:
    """PATCH .../items/{item_id} — see ADR-0007 п.3. An explicit null clears
    confirmed_at along with confirmed_price, rather than leaving a stale
    timestamp next to an empty price."""
    item = db.get(OrderItem, item_id)
    if item is None or item.order_id != order_id:
        raise OrderItemNotFoundError(order_id, item_id)

    item.confirmed_price = confirmed_price
    item.confirmed_at = datetime.now(timezone.utc) if confirmed_price is not None else None
    db.commit()
    db.refresh(item)
    return item
