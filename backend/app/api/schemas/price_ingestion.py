"""Pydantic schemas for price-list upload/review/apply — see ADR-0019 §5."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, model_validator


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
    possible_duplicate_of: list[uuid.UUID] = []
    processing_status: str | None = None


class PriceListImportOut(BaseModel):
    import_id: uuid.UUID
    status: str
    entries: list[PriceListEntryOut]


class ApplyEntryIn(BaseModel):
    action: Literal["match", "new", "skip"]
    material_id: uuid.UUID | None = None
    internal_sku: str | None = None
    canonical_name: str | None = None

    @model_validator(mode="after")
    def _check_required_fields_for_action(self) -> ApplyEntryIn:
        if self.action == "match" and self.material_id is None:
            raise ValueError("material_id is required when action is 'match'")
        if self.action == "new" and (self.internal_sku is None or self.canonical_name is None):
            raise ValueError(
                "internal_sku and canonical_name are required when action is 'new'"
            )
        return self
