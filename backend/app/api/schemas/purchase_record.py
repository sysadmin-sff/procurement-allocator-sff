"""Pydantic-схемы для PurchaseRecord — см. ADR-0008.

GET .../purchase-records возвращает единый объект {records, project_total,
supplier_totals}, не отдельные endpoint'ы для списка и агрегатов: план/факт
контроль (ADR-0008 п.4) — это ровно то, ради чего открывается этот экран
("Фактическая закупка", ADR-0008 п.5), агрегаты и записи всегда читаются
вместе на одном экране, а не по отдельности. Разделение на два запроса
добавило бы round-trip без сценария, где нужен только один из двух кусков.

planned_total/delta/delta_pct — None (не 0), если для project/supplier ещё
нет ни одного Order — нет базы для сравнения, см. ADR-0008 п.4.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PurchaseRecordCreate(BaseModel):
    supplier_id: uuid.UUID
    raw_description: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)
    material_id: uuid.UUID | None = None


class PurchaseRecordUpdate(BaseModel):
    supplier_id: uuid.UUID
    raw_description: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)
    material_id: uuid.UUID | None = None


class PurchaseRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    supplier_id: uuid.UUID
    raw_description: str
    quantity: int
    unit_price: float
    material_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime


class TotalComparisonOut(BaseModel):
    purchased_total: float
    planned_total: float | None = None
    delta: float | None = None
    delta_pct: float | None = None


class SupplierTotalOut(TotalComparisonOut):
    supplier_id: uuid.UUID


class PurchaseRecordListOut(BaseModel):
    records: list[PurchaseRecordOut]
    project_total: TotalComparisonOut
    supplier_totals: list[SupplierTotalOut]
