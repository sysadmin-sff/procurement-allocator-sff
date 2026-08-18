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
from sqlalchemy.orm import Session

from app.models import AllocationLine, AllocationRun, Order, OrderItem

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


def create_orders_for_run(
    db: Session, project_id: uuid.UUID, run_id: uuid.UUID
) -> list[Order]:
    """Create one Order per supplier in the run's current supplier_summaries
    (i.e. after any ADR-0006 overrides), snapshotting each supplier's current
    AllocationLine rows into OrderItem. Marks every line that went into an
    Order with ordered_at. Not deduplicated against prior Order creation for
    the same run — see ADR-0007 п.2 "Отклонено": a re-order/partial reorder
    is a legitimate real-world scenario, not a bug to guard against.
    """
    run = db.get(AllocationRun, run_id)
    if run is None or run.project_id != project_id:
        raise RunNotFoundError(project_id, run_id)

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
