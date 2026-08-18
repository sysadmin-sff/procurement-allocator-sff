"""Pydantic-схемы ответа для /projects/{project_id}/allocate и .../allocations/{run_id}.

Отдельно от ORM-моделей (app/models/allocation.py) — API-контракт не обязан
дословно повторять структуру таблиц (например, orphaned_materials хранится
как сырой JSON-список dict, здесь он типизирован явной схемой).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AllocationLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    material_id: uuid.UUID
    supplier_id: uuid.UUID
    quantity: int
    unit_price: float
    line_total: float
    overridden_at: datetime | None = None
    original_supplier_id: uuid.UUID | None = None
    original_unit_price: float | None = None


class AllocationLineOverrideIn(BaseModel):
    """Body for PATCH .../lines/{line_id} — see ADR-0006 п.5. Single-field,
    no diff-semantics, same style as ProjectUpdate (ADR-0004)."""

    supplier_id: uuid.UUID


class OrphanedMaterialOut(BaseModel):
    material_id: uuid.UUID
    required_quantity: int
    best_partial_supplier_id: uuid.UUID | None = None
    best_partial_available: int | None = None


class SupplierAllocationSummaryOut(BaseModel):
    """Сводка доставки по одному задействованному поставщику — order_total[s]
    и free[s] из ADR-0002, экспортированные наружу солвером."""

    supplier_id: uuid.UUID
    goods_total: float
    delivery_fee: float
    free_shipping_achieved: bool
    below_min_order: bool = False
    """True если goods_total ниже Supplier.delivery_policy.per_order_min_amount
    — при обычном run_allocation() всегда False (ADR-0002 Ограничение 4 —
    жёсткое условие ILP), может стать True только после ручного
    переопределения (ADR-0006), которое не подчиняется этому ограничению."""


class AllocationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    created_at: datetime
    algorithm_version: str | None
    status: str
    lines: list[AllocationLineOut]
    orphaned_materials: list[OrphanedMaterialOut]
    supplier_summaries: list[SupplierAllocationSummaryOut]
