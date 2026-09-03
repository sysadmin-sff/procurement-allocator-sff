"""Pydantic-схемы для Order/OrderItem — см. ADR-0007.

quoted_price/confirmed_price — раздельные снимок и сверка, не одно поле
unit_price (переименовано под ADR-0007 п.1). price_delta/price_delta_pct —
вычисляются на чтении (app/allocation/order_service.py), не хранятся в БД.

received_price/declined_at/decline_reason — см. ADR-0013. received_price
не имеет собственного price_delta аналога (ADR-0013 п.4: только quoted vs
confirmed остаётся вычисляемым показателем).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    material_id: uuid.UUID
    quantity: int
    quoted_price: float
    received_price: float | None = None
    target_price: float | None = None
    """Наша целевая цена для торга — не факт от поставщика. См. ADR-0027 п.1."""
    confirmed_price: float | None = None
    confirmed_at: datetime | None = None
    declined_at: datetime | None = None
    decline_reason: str | None = None
    price_delta: float | None = None
    price_delta_pct: float | None = None
    received_price_delta: float | None = None
    received_price_delta_pct: float | None = None
    """quoted vs received (не quoted vs confirmed, как price_delta) — см.
    ADR-0027 §3. NULL при received_price IS NULL, не 0."""
    replaced_by_supplier_id: uuid.UUID | None = None
    replaced_by_supplier_name: str | None = None
    """Derived, not persisted — see ADR-0014 п.3. Set only when the latest
    AllocationRun's line for this item's material has
    overridden_via_order_item_id == this item's id (a causal replacement
    triggered by this declined item, not a timestamp coincidence). Null if
    no replacement happened, the material dropped out of the latest run, or
    the line was since overridden again by an unrelated PATCH."""
    replacement_draft_order_id: uuid.UUID | None = None
    """Non-null if replaced_by_supplier_id has an existing draft Order in
    this project (reuses ADR-0012's conflict check) — see ADR-0014 п.3."""


class OrderItemConfirmIn(BaseModel):
    """Body for PATCH /orders/{order_id}/items/{item_id} — see ADR-0007 п.3
    and ADR-0013 п.3. Every field is independently optional: omitting a
    field leaves it untouched; passing null explicitly clears it (for
    confirmed_price/received_price) or, for declined, false clears
    declined_at/decline_reason. Field omitted vs field=null is
    distinguished server-side via `model_fields_set` in the API handler,
    not by this schema alone."""

    confirmed_price: float | None = Field(default=None)
    received_price: float | None = Field(default=None)
    target_price: float | None = Field(default=None)
    declined: bool | None = Field(default=None)
    decline_reason: str | None = Field(default=None)


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    supplier_id: uuid.UUID
    status: str
    total_amount: float
    delivery_fee: float
    items: list[OrderItemOut]
    expected_goods_total: float
    expected_delivery_fee: float
    expected_total: float
    declined_amount: float
    fully_declined: bool
    """Derived, not persisted — see ADR-0026. total_amount/delivery_fee stay
    the ADR-0007 §2 snapshot unchanged; these fields compute what the order
    now amounts to after declined items (ADR-0013), summed from quoted_price
    (same scale as total_amount, not confirmed_price/received_price — see
    ADR-0026 п.1). expected_delivery_fee is the delivery_fee snapshot as-is
    unless every item is declined, in which case it is 0 (nothing left to
    ship) — never recomputed against the supplier's free-shipping threshold
    for a partial decline (ADR-0026 п.4)."""


class CreateOrdersIn(BaseModel):
    """Body for POST .../orders — see ADR-0012 п.2. replace_drafts=True
    deletes conflicting suppliers' existing draft Order/OrderItem rows
    before creating; default False surfaces a 409 instead of creating
    anything when a conflict exists.

    acknowledge_conflict=True means "I saw the 409 and want the additional
    order anyway": creation proceeds, nothing is deleted, the existing
    drafts stay alongside the new Orders. It is deliberately a field of its
    own rather than a reuse of replace_drafts=False — the endpoint is
    stateless and replace_drafts=False cannot distinguish "not asked yet"
    from "asked and confirmed", which is exactly the gap recorded in
    ADR-0012 "Отклонение реализации от принятого решения" and the follow-up
    in docs/known-issues.md."""

    replace_drafts: bool = False
    acknowledge_conflict: bool = False


class ExistingDraftOrderOut(BaseModel):
    """One entry in a supplier's existing_draft_orders — see ADR-0012 п.4.
    has_confirmed_prices is true if any OrderItem on *this* draft Order has
    confirmed_price set; replacing such a draft loses data that cannot be
    recovered from AllocationLine."""

    order_id: uuid.UUID
    total_amount: float
    has_confirmed_prices: bool


class SupplierWithExistingDraftsOut(BaseModel):
    supplier_id: uuid.UUID
    supplier_name: str
    existing_draft_orders: list[ExistingDraftOrderOut]


class OrderDraftConflictOut(BaseModel):
    """409 response body when create_orders_for_run finds pre-existing draft
    Orders for one or more suppliers in the run and neither replace_drafts
    nor acknowledge_conflict is True — see ADR-0012 п.4."""

    detail: str = "draft_orders_exist"
    suppliers_with_existing_drafts: list[SupplierWithExistingDraftsOut]


class ReplacementCandidateOut(BaseModel):
    """One supplier candidate for POST .../find-replacement — see ADR-0014
    п.1. All active-priced suppliers are included, even those with
    insufficient/unknown availability (visible-risk philosophy, same as
    ADR-0006 п.2) — availability_risk is True only when availability is
    explicitly set and less than the declined item's quantity; NULL
    availability is never a risk (symmetric with ADR-0005)."""

    supplier_id: uuid.UUID
    supplier_name: str
    price: float
    availability: int | None
    availability_risk: bool


class FindReplacementOut(BaseModel):
    """Response body for POST .../find-replacement — see ADR-0014 п.5.
    line_id is the AllocationLine in the project's latest AllocationRun for
    this item's material, which the frontend then PATCHes (ADR-0006) with
    source_order_item_id set to attribute the override to this decline."""

    line_id: uuid.UUID
    candidates: list[ReplacementCandidateOut]


class ReplaceAndOrderIn(BaseModel):
    """Body for POST .../items/{item_id}/replace-and-order — see ADR-0015 §1.
    supplier_id is the chosen replacement candidate (one of
    FindReplacementOut.candidates from the prior find-replacement call)."""

    supplier_id: uuid.UUID
