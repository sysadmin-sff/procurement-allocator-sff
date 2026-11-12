"""Pydantic-схемы для CRUD /prices.

price выражена в долларах (Numeric(12,2) в БД) — конвертация в центы
происходит только внутри allocation-слоя, не здесь.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PriceCreate(BaseModel):
    material_id: uuid.UUID
    supplier_id: uuid.UUID
    price: float
    currency: str = "USD"
    availability: int | None = Field(default=None, ge=0)
    min_order_qty: int | None = Field(default=None, ge=0)
    valid_from: date
    valid_to: date | None = None

    @model_validator(mode="after")
    def _check_date_order(self) -> PriceCreate:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not be before valid_from")
        return self


class PriceUpdate(BaseModel):
    """Частичное обновление: поля, не переданные в payload, наследуются от
    закрываемой строки, а не сбрасываются на дефолт — см. update_price.
    valid_from обязателен: у новой версионированной строки не может быть
    даты начала действия по умолчанию."""

    price: float | None = None
    currency: str | None = None
    availability: int | None = Field(default=None, ge=0)
    min_order_qty: int | None = Field(default=None, ge=0)
    valid_from: date
    valid_to: date | None = None

    @model_validator(mode="after")
    def _check_date_order(self) -> PriceUpdate:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not be before valid_from")
        return self


class PriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    material_id: uuid.UUID
    supplier_id: uuid.UUID
    price: float
    currency: str
    availability: int | None
    min_order_qty: int | None
    valid_from: date
    valid_to: date | None
    source_import_id: uuid.UUID | None


# --- Матрица цен и история пары (ADR-0054) ---------------------------------

ChangeKind = Literal["up", "down", "same", "new"]


class ChangeCountsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    up: int
    down: int
    new: int
    same: int


class MatrixCellOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    supplier_id: uuid.UUID
    price_id: uuid.UUID
    price: float
    currency: str
    valid_from: date
    baseline_price: float | None
    baseline_valid_from: date | None
    change: ChangeKind
    change_pct: float | None
    is_cheapest: bool


class MatrixRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    material_id: uuid.UUID
    internal_sku: str
    canonical_name: str
    unit: str
    category_name: str | None
    cells: list[MatrixCellOut]


class MatrixSupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    short_name: str | None
    is_active_for_allocation: bool
    last_price_date: date | None
    days_since_update: int | None
    is_stale: bool
    active_price_count: int
    changes: ChangeCountsOut


class PriceMatrixOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of: date
    compare_to: date | None
    stale_after_days: int
    suppliers: list[MatrixSupplierOut]
    rows: list[MatrixRowOut]
    summary: ChangeCountsOut


class PriceHistoryEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    price: float
    currency: str
    valid_from: date
    valid_to: date | None
    source: Literal["import", "order", "manual"]
    import_id: uuid.UUID | None
    import_uploaded_at: datetime | None
    order_id: uuid.UUID | None
    order_title: str | None
    created_by_name: str | None
    change: ChangeKind | None
