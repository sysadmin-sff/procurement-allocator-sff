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

from app.allocation.service import InvalidOverrideSupplierError, override_allocation_line_supplier
from app.models import (
    AllocationLine,
    AllocationRun,
    Material,
    Order,
    OrderItem,
    Price,
    Project,
    Supplier,
)

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


class MaterialNotInLatestRunError(Exception):
    """The declined item's material has no AllocationLine in the project's
    latest AllocationRun — the BOM or plan changed since this Order was
    created, so there is nothing to override. See ADR-0014 п.2."""

    def __init__(self, order_item_id: uuid.UUID, material_name: str):
        self.order_item_id = order_item_id
        self.material_name = material_name
        super().__init__(
            f"Material {material_name} is not present in the project's current "
            "allocation plan — the plan may have changed since this order was created"
        )


class DraftOrderConflictError(Exception):
    """Raised when create_orders_for_run() is called with neither
    replace_drafts nor acknowledge_conflict while at least one supplier in
    the run's supplier_summaries already has a draft Order in this project
    from a prior run — see ADR-0012 п.1/п.2.

    suppliers_with_existing_drafts mirrors the 409 body shape exactly (list
    per supplier, list of existing_draft_orders per supplier — never a single
    object, real dev data has suppliers with more than one, see ADR-0012
    "Контекст") so the API layer can serialize it without recomputing.
    """

    def __init__(self, suppliers_with_existing_drafts: list[dict]):
        self.suppliers_with_existing_drafts = suppliers_with_existing_drafts
        super().__init__("Draft orders already exist for one or more suppliers in this run")


class MultipleDraftOrdersConflictError(Exception):
    """Raised by replace_and_sync_order() when the target supplier already
    has more than one draft Order in this project — ADR-0015 §1 step 3,
    "больше одного". No draft is picked automatically (id/created_at give no
    deterministic, meaningful ordering — same instinct as ADR-0012's refusal
    to guess); resolution is manual. Raised before any write happens, so the
    caller never needs to roll back the AllocationLine override."""

    def __init__(self, supplier_id: uuid.UUID, supplier_name: str, count: int):
        self.supplier_id = supplier_id
        self.supplier_name = supplier_name
        self.count = count
        super().__init__(
            f"У поставщика {supplier_name} уже есть {count} черновика ордеров по этому "
            "проекту — сначала определитесь, какой из них актуален, прежде чем "
            "переносить сюда позицию."
        )


class DuplicateMaterialInDraftError(Exception):
    """Raised by replace_and_sync_order() when the target draft Order already
    has an OrderItem for this material — ADR-0015 §1 step 3, last bullet.
    Not auto-merged (unclear whether to sum quantity or which price wins) —
    same reasoning as MultipleDraftOrdersConflictError. Raised before any
    write happens."""

    def __init__(self, order_id: uuid.UUID, material_id: uuid.UUID, material_name: str):
        self.order_id = order_id
        self.material_id = material_id
        self.material_name = material_name
        super().__init__(
            f'В черновике ордера этого поставщика уже есть позиция "{material_name}" — '
            "сначала объедините или уберите её вручную, прежде чем переносить сюда ещё одну."
        )


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


def _latest_allocation_run(db: Session, project_id: uuid.UUID) -> AllocationRun | None:
    """Same query as get_project() (app/api/project.py) — the most recent
    AllocationRun for a project, not necessarily the run that created any
    particular Order. See ADR-0014 п.2."""
    return (
        db.query(AllocationRun)
        .filter(AllocationRun.project_id == project_id)
        .order_by(AllocationRun.created_at.desc())
        .first()
    )


def find_replacement_candidates(
    db: Session, order_id: uuid.UUID, item_id: uuid.UUID
) -> tuple[uuid.UUID, list[dict]]:
    """POST .../items/{item_id}/find-replacement — ADR-0014 п.1/п.2/п.5.

    Locates the AllocationLine for this item's material in the project's
    *latest* AllocationRun (which may differ from the run that created this
    Order — the plan can change afterward), then returns every supplier with
    an active Price on that material, each flagged with an explicit
    availability risk (availability set and less than the line's quantity;
    NULL availability is never a risk, symmetric with ADR-0005/ADR-0006 п.2).

    Returns (line_id, candidates) — line_id lets the frontend PATCH
    .../lines/{line_id} directly without a second lookup.
    """
    item = db.get(OrderItem, item_id)
    if item is None or item.order_id != order_id:
        raise OrderItemNotFoundError(order_id, item_id)

    order = db.get(Order, order_id)
    run = _latest_allocation_run(db, order.project_id)
    line = (
        db.scalars(
            select(AllocationLine).where(
                AllocationLine.allocation_run_id == run.id,
                AllocationLine.material_id == item.material_id,
            )
        ).first()
        if run is not None
        else None
    )
    if line is None:
        material = db.get(Material, item.material_id)
        raise MaterialNotInLatestRunError(item_id, material.canonical_name)

    prices = db.scalars(
        select(Price).where(
            Price.material_id == item.material_id,
            Price.valid_to.is_(None),
        )
    ).all()
    suppliers = db.scalars(
        select(Supplier).where(Supplier.id.in_({p.supplier_id for p in prices}))
    ).all()
    names_by_id = {s.id: s.name for s in suppliers}

    candidates = [
        {
            "supplier_id": price.supplier_id,
            "supplier_name": names_by_id[price.supplier_id],
            "price": float(price.price),
            "availability": price.availability,
            "availability_risk": price.availability is not None
            and price.availability < line.quantity,
        }
        for price in prices
    ]
    return line.id, candidates


def replacement_info_for_item(
    db: Session, item: OrderItem
) -> tuple[uuid.UUID | None, str | None, uuid.UUID | None]:
    """Derived (not persisted) fields for OrderItemOut — ADR-0014 п.3.

    Returns (replaced_by_supplier_id, replaced_by_supplier_name,
    replacement_draft_order_id). All None unless the project's *latest*
    AllocationRun has a line for this item's material whose
    overridden_via_order_item_id points at exactly this item — the causal
    attribution set by the find-replacement PATCH, not a timestamp
    coincidence (see ADR-0014 п.3 for why overridden_at > declined_at was
    rejected).
    """
    order = db.get(Order, item.order_id)
    run = _latest_allocation_run(db, order.project_id)
    if run is None:
        return None, None, None

    line = db.scalars(
        select(AllocationLine).where(
            AllocationLine.allocation_run_id == run.id,
            AllocationLine.material_id == item.material_id,
        )
    ).first()
    if line is None or line.overridden_via_order_item_id != item.id:
        return None, None, None

    supplier = db.get(Supplier, line.supplier_id)
    conflicts = _conflicting_draft_orders_by_supplier(db, order.project_id, {supplier.id})
    existing_drafts = conflicts.get(supplier.id, [])
    draft_order_id = existing_drafts[0].id if existing_drafts else None

    return supplier.id, supplier.name, draft_order_id


def replace_and_sync_order(
    db: Session,
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    supplier_id: uuid.UUID,
    overridden_by_user_id: uuid.UUID | None = None,
) -> OrderItem:
    """POST .../items/{item_id}/replace-and-order — ADR-0015 §1.

    One transaction: overrides the AllocationLine for this item's material in
    the project's latest AllocationRun to supplier_id, then adds/creates the
    matching draft Order for that supplier with the reassigned line as a new
    OrderItem, and recomputes that one Order's total_amount/delivery_fee from
    the same run's supplier_summaries (no separate delivery formula — ADR-0015
    §1 step 4).

    All conflict checks (multiple existing drafts for supplier_id, or a
    duplicate material_id in the single existing draft) run *before* calling
    override_allocation_line_supplier() — that call commits internally
    (app.allocation.service), so there is no in-process rollback available
    once it has run; ordering the checks first is what makes "conflict ->
    override not applied" hold, not a try/except around a commit.

    Raises (same as find_replacement_candidates): OrderItemNotFoundError,
    MaterialNotInLatestRunError. Raises MultipleDraftOrdersConflictError or
    DuplicateMaterialInDraftError when the target draft can't unambiguously
    receive the new line — nothing is written in either case.
    """
    line_id, candidates = find_replacement_candidates(db, order_id, item_id)
    line_before = db.get(AllocationLine, line_id)
    candidate = next((c for c in candidates if c["supplier_id"] == supplier_id), None)
    if candidate is None:
        raise InvalidOverrideSupplierError(line_before.material_id, supplier_id)

    item = db.get(OrderItem, item_id)
    order = db.get(Order, order_id)

    existing_drafts = db.scalars(
        select(Order)
        .options(selectinload(Order.items))
        .where(
            Order.project_id == order.project_id,
            Order.supplier_id == supplier_id,
            Order.status == "draft",
        )
    ).all()

    if len(existing_drafts) > 1:
        supplier = db.get(Supplier, supplier_id)
        raise MultipleDraftOrdersConflictError(supplier_id, supplier.name, len(existing_drafts))

    target_order = existing_drafts[0] if existing_drafts else None
    if target_order is not None and any(
        oi.material_id == item.material_id for oi in target_order.items
    ):
        material = db.get(Material, item.material_id)
        raise DuplicateMaterialInDraftError(target_order.id, item.material_id, material.canonical_name)

    line = override_allocation_line_supplier(
        db,
        run_id=line_before.allocation_run_id,
        line_id=line_id,
        new_supplier_id=supplier_id,
        source_order_item_id=item_id,
        overridden_by_user_id=overridden_by_user_id,
    )

    if target_order is None:
        target_order = Order(
            project_id=order.project_id,
            supplier_id=supplier_id,
            status="draft",
            total_amount=0,
            delivery_fee=0,
        )
        db.add(target_order)
        db.flush()

    db.add(
        OrderItem(
            order_id=target_order.id,
            material_id=line.material_id,
            quantity=line.quantity,
            quoted_price=candidate["price"],
        )
    )
    db.flush()

    run = db.get(AllocationRun, line.allocation_run_id)
    summary = next(
        s for s in run.supplier_summaries if s["supplier_id"] == str(supplier_id)
    )
    target_order.total_amount = summary["goods_total"]
    target_order.delivery_fee = summary["delivery_fee"]

    db.commit()
    db.refresh(item)
    return item


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
    db: Session,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    replace_drafts: bool = False,
    acknowledge_conflict: bool = False,
    created_by_user_id: uuid.UUID | None = None,
) -> list[Order]:
    """Create one Order per supplier in the run's current supplier_summaries
    (i.e. after any ADR-0006 overrides), snapshotting each supplier's current
    AllocationLine rows into OrderItem. Marks every line that went into an
    Order with ordered_at.

    Guards against accidental duplicate draft Orders — see ADR-0012. Before
    inserting, checks (per supplier in this run) whether a draft Order for
    that supplier already exists elsewhere in this project:
    - No conflicts: proceeds as before (ADR-0007 п.2's "re-order is
      legitimate" is unchanged — this only gates the *default*,
      unconfirmed path, not re-ordering itself).
    - Conflicts and neither replace_drafts nor acknowledge_conflict is
      True: raises DraftOrderConflictError, creates and deletes nothing.
    - replace_drafts=True: deletes the conflicting suppliers' existing draft
      Order/OrderItem rows (application-level cascade, no DB-level
      ON DELETE CASCADE exists for order_items.order_id) before the normal
      creation logic runs, in the same transaction. Suppliers without a
      conflict (new in this run) are unaffected. approved/sent Orders are
      never conflicts and are never touched, at any replace_drafts value.
    - acknowledge_conflict=True (and replace_drafts not True): the caller
      has already seen this conflict and explicitly wants the additional
      order — creation proceeds exactly as in the no-conflict case, nothing
      is deleted, the existing drafts (including any confirmed_price on
      them) stay intact alongside the new Orders. This is the "создать
      дополнительно" path of ADR-0012 §1/§2, which the original contract
      could not express: the endpoint is stateless, so replace_drafts=False
      alone cannot distinguish "user not asked yet" from "user asked and
      explicitly wants the extra order" — hence a separate field rather
      than a reused one. See ADR-0012 "Отклонение реализации от принятого
      решения" and the follow-up in docs/known-issues.md.

    replace_drafts takes precedence if both are True: it is the more
    specific instruction, and either flag alone already means the user has
    seen the conflict.
    """
    run = db.get(AllocationRun, run_id)
    if run is None or run.project_id != project_id:
        raise RunNotFoundError(project_id, run_id)

    supplier_ids = {uuid.UUID(summary["supplier_id"]) for summary in run.supplier_summaries}
    conflicts = _conflicting_draft_orders_by_supplier(db, project_id, supplier_ids)

    if conflicts:
        if replace_drafts:
            _delete_orders(db, [order for orders in conflicts.values() for order in orders])
            db.flush()
        elif not acknowledge_conflict:
            raise DraftOrderConflictError(_serialize_conflicts(db, conflicts))
        # else: acknowledged additional order — fall through to the normal
        # creation path, deleting nothing (ADR-0012 §1 "создать дополнительно").

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
            created_by_user_id=created_by_user_id,
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


_UNSET = object()
"""Sentinel distinguishing "field omitted from PATCH" (leave untouched)
from "field explicitly set to None" (clear it) — needed because every new
field on this endpoint is independently optional, same semantics
confirmed_price already had alone. See ADR-0013 п.3."""


def set_order_item_fields(
    db: Session,
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    confirmed_price: float | None = _UNSET,
    received_price: float | None = _UNSET,
    declined: bool | None = _UNSET,
    decline_reason: str | None = _UNSET,
) -> OrderItem:
    """PATCH .../items/{item_id} — see ADR-0007 п.3 and ADR-0013 п.3. Each
    keyword is independently optional: omit it (leave at the _UNSET
    default) to leave that field untouched, or pass None explicitly to
    clear it. declined=True stamps declined_at=now(); declined=False clears
    declined_at and decline_reason together. No field here validates
    against any other — declined_at may coexist with received_price/
    confirmed_price (ADR-0013 п.2), and confirmed_price may be set without
    received_price ever being set (ADR-0013 п.1)."""
    item = db.get(OrderItem, item_id)
    if item is None or item.order_id != order_id:
        raise OrderItemNotFoundError(order_id, item_id)

    if confirmed_price is not _UNSET:
        item.confirmed_price = confirmed_price
        item.confirmed_at = datetime.now(timezone.utc) if confirmed_price is not None else None

    if received_price is not _UNSET:
        item.received_price = received_price

    if declined is not _UNSET:
        if declined:
            item.declined_at = datetime.now(timezone.utc)
        else:
            item.declined_at = None
            item.decline_reason = None

    if decline_reason is not _UNSET:
        item.decline_reason = decline_reason

    db.commit()
    db.refresh(item)
    return item
