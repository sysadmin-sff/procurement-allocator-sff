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
