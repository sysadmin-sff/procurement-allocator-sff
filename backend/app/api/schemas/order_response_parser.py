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
    matched_by_alias: bool
    """True only for a line the post-match step linked via a stored
    SupplierMaterialAlias (ADR-0046 §1), not the model itself — confidence
    is left untouched either way (see ADR-0046 §1 "Почему confidence не
    меняется"), this is the only API-visible signal of the source."""


class MissingItemOut(BaseModel):
    order_item_id: uuid.UUID
    material_id: uuid.UUID | None
    canonical_name: str
    """item.material.canonical_name, or item.raw_description for a
    lightweight OrderItem without a catalog material — see ADR-0033 §3."""
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


class CreateResponseAliasIn(BaseModel):
    """Body for POST /orders/{order_id}/response-aliases — see ADR-0046 §2.
    supplier_raw_name is taken verbatim from the "extra" line's
    raw_description (ExtractedLine has no separate sku field — see
    ADR-0046 "Схема извлечённой строки модели"), not parsed."""

    supplier_raw_name: str
    supplier_sku: str | None = None
    material_id: uuid.UUID
    force: bool = False


class ExistingAliasOut(BaseModel):
    """409 conflict body — the alias already stored for this exact
    (supplier_id, supplier_raw_name, origin='order_response'), with a
    different material_id than the one just submitted."""

    material_id: uuid.UUID
    canonical_name: str
    created_at: str | None


class ResponseAliasOut(BaseModel):
    id: uuid.UUID
    supplier_id: uuid.UUID
    material_id: uuid.UUID
    supplier_raw_name: str
    supplier_sku: str | None
    origin: str
