"""Pydantic-схемы для CRUD /prices.

price выражена в долларах (Numeric(12,2) в БД) — конвертация в центы
происходит только внутри allocation-слоя, не здесь.
"""

from __future__ import annotations

import uuid
from datetime import date

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
