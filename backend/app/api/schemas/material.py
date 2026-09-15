from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class MaterialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str
    category_id: uuid.UUID
    unit: str
    attributes: dict = {}


class MaterialUpdate(BaseModel):
    """Частичное обновление: поля, не переданные в payload, сохраняют текущее
    значение в БД, а не сбрасываются на дефолт — см. update_material.
    internal_sku исключён полностью — SKU выдаётся один раз при создании и
    не пересчитывается при последующей переклассификации, см. ADR-0034 п.4."""

    model_config = ConfigDict(extra="forbid")

    canonical_name: str | None = None
    category_id: uuid.UUID | None = None
    unit: str | None = None
    attributes: dict | None = None


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    internal_sku: str
    canonical_name: str
    category_name: str
    unit: str
    attributes: dict
    color_options: list[str] | None = None
    color_fragment: str | None = None
