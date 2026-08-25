"""Pydantic schemas for POST /orders/{order_id}/parse-response — see ADR-0018 §3.

Read-only preview response, three categories: matched (all confidence
levels), missing (this Order's OrderItem with no matching line), extra
(unmatched lines). Nothing here is persisted by this endpoint — the frontend
applies matched/extra via the existing PATCH .../items/{item_id} (ADR-0007
§3, ADR-0013 §3) and POST .../purchase-records (ADR-0008 §5) endpoints.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class MatchedLineOut(BaseModel):
    order_item_id: uuid.UUID
    raw_description: str
    price: float
    quantity: int | None
    confidence: str
    reasoning: str


class MissingItemOut(BaseModel):
    order_item_id: uuid.UUID
    material_id: uuid.UUID
    canonical_name: str
    quantity: int
    quoted_price: float


class ExtraLineOut(BaseModel):
    raw_description: str
    price: float
    quantity: int | None
    confidence: str
    reasoning: str


class ParseOrderResponseOut(BaseModel):
    matched: list[MatchedLineOut]
    missing: list[MissingItemOut]
    extra: list[ExtraLineOut]
