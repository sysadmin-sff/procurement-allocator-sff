"""Pydantic schemas for price-list upload/review/apply — see ADR-0019 §5."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel


class PriceListEntryOut(BaseModel):
    id: uuid.UUID
    supplier_raw_name: str
    supplier_sku: str | None
    matched_material_id: uuid.UUID | None
    confidence: float | None
    reasoning: str | None
    price: float
    currency: str
    availability: int | None
    min_order_qty: int | None
    action: str | None
    suggested_internal_sku: str | None = None
    possible_duplicate_of: list[uuid.UUID] = []


class PriceListImportOut(BaseModel):
    import_id: uuid.UUID
    status: str
    entries: list[PriceListEntryOut]


class ApplyEntryIn(BaseModel):
    action: Literal["match", "new", "skip"]
    material_id: uuid.UUID | None = None
    internal_sku: str | None = None
    canonical_name: str | None = None
