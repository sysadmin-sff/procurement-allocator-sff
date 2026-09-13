from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProjectTemplateCreate(BaseModel):
    name: str


class ProjectTemplateUpdate(BaseModel):
    name: str


class ProjectTemplateItemCreate(BaseModel):
    material_id: uuid.UUID


class ProjectTemplateItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    material_id: uuid.UUID
    canonical_name: str
    unit: str
    category: str | None


class ProjectTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    items: list[ProjectTemplateItemOut]
