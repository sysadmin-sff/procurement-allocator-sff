from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    sku_prefix: str
    requires_single_supplier: bool = False


class CategoryUpdate(BaseModel):
    """sku_prefix отсутствует намеренно — неизменяем после создания, см.
    ADR-0034 п.5. Не просто игнорируется: поле физически отсутствует в схеме."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    requires_single_supplier: bool | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    sku_prefix: str
    requires_single_supplier: bool
    next_sku_number: int
    created_at: datetime
