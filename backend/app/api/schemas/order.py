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
    confirmed_price: float | None = None
    confirmed_at: datetime | None = None
    declined_at: datetime | None = None
    decline_reason: str | None = None
    price_delta: float | None = None
    price_delta_pct: float | None = None


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


class CreateOrdersIn(BaseModel):
    """Body for POST .../orders — see ADR-0012 п.2. replace_drafts=True
    deletes conflicting suppliers' existing draft Order/OrderItem rows
    before creating; default False surfaces a 409 instead of creating
    anything when a conflict exists."""

    replace_drafts: bool = False


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
    Orders for one or more suppliers in the run and replace_drafts is not
    True — see ADR-0012 п.4."""

    detail: str = "draft_orders_exist"
    suppliers_with_existing_drafts: list[SupplierWithExistingDraftsOut]
