"""Pydantic-схемы для проектов и позиций спецификации (ProjectItem).

Проект поддерживает create/read и обновление title (см. ADR-0004 — автосохранение
черновика по мере ввода). status не редактируется напрямую через API. Позиции
(ProjectItem) поддерживают полный CRUD — редактируются с экрана просмотра проекта."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    title: str
    created_by: str | None = None


class ProjectUpdate(BaseModel):
    title: str


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_by: str | None
    status: str
    created_at: datetime


class ProjectItemCreate(BaseModel):
    material_id: uuid.UUID
    quantity: int = Field(gt=0)


class ProjectItemUpdate(BaseModel):
    quantity: int = Field(gt=0)


class ProjectItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    material_id: uuid.UUID
    quantity: int


class LatestAllocationRunOut(BaseModel):
    """Сводка последнего AllocationRun проекта — только то, что нужно экрану
    просмотра проекта, чтобы решить "Рассчитать" или "Пересчитать" показывать,
    без похода за полным AllocationRunOut (lines/orphaned_materials/summaries)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    status: str


class ProjectWithItemsOut(ProjectOut):
    items: list[ProjectItemOut]
    latest_allocation_run: LatestAllocationRunOut | None = None


class PlanCandidateOut(BaseModel):
    """One supplier's active Price for a material, in the "План" section of
    GET .../price-comparison — see ADR-0016 §1/§4. is_cheapest is computed
    purely by price, independent of availability (ADR-0016 §4) — a candidate
    with insufficient/unknown availability can still be is_cheapest."""

    supplier_id: uuid.UUID
    supplier_name: str
    price: float
    availability: int | None
    is_cheapest: bool


class SupplierResponseOut(BaseModel):
    """One supplier's Order-derived response for a material, in the "Ответы
    поставщиков" section of GET .../price-comparison — see ADR-0016 §1/§3/§4.
    Only suppliers with at least one Order containing this material appear.
    When a supplier has multiple Orders containing the material, the row is
    taken from the Order with the maximum created_at among those that
    actually contain it (ADR-0016 §3). is_cheapest compares the effective
    price (confirmed_price, else received_price, else quoted_price) among
    declined_at IS NULL rows only — a declined row is never is_cheapest even
    if its received_price is the lowest in the row (ADR-0016 §4)."""

    supplier_id: uuid.UUID
    supplier_name: str
    quoted_price: float
    received_price: float | None
    confirmed_price: float | None
    declined_at: datetime | None
    decline_reason: str | None
    is_cheapest: bool


class MaterialComparisonRowOut(BaseModel):
    """Comparison data for one ProjectItem (material), keyed to it by
    project_item_id so the frontend can align both sections' rows without a
    separate material lookup."""

    project_item_id: uuid.UUID
    material_id: uuid.UUID
    plan: list[PlanCandidateOut]
    supplier_responses: list[SupplierResponseOut]


class PriceComparisonOut(BaseModel):
    """Response body for GET /projects/{project_id}/price-comparison — see
    ADR-0016. One row per ProjectItem in the project; both `plan` and
    `supplier_responses` are always present on every row (empty lists, not
    omitted), even when a material has no active Price anywhere or the
    project has no Order yet — ADR-0016 §1."""

    rows: list[MaterialComparisonRowOut]
