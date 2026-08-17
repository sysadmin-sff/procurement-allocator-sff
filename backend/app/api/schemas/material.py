from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class MaterialCreate(BaseModel):
    internal_sku: str
    canonical_name: str
    category: str | None = None
    unit: str
    attributes: dict = {}


class MaterialUpdate(BaseModel):
    """Частичное обновление: поля, не переданные в payload, сохраняют текущее
    значение в БД, а не сбрасываются на дефолт — см. update_material."""

    internal_sku: str | None = None
    canonical_name: str | None = None
    category: str | None = None
    unit: str | None = None
    attributes: dict | None = None


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    internal_sku: str
    canonical_name: str
    category: str | None
    unit: str
    attributes: dict
