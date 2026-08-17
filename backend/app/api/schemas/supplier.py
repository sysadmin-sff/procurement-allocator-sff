"""Pydantic-схемы для CRUD /suppliers.

delivery_policy типизирован явной подсхемой (а не сырым dict), чтобы API
валидировал форму на входе — поля соответствуют ADR-0002 (flat_fee,
free_shipping_threshold, per_order_min_amount, lead_time_days).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class DeliveryPolicy(BaseModel):
    flat_fee: float = 0.0
    free_shipping_threshold: float | None = None
    """None = бесплатная доставка не настроена (никогда не бесплатно); 0 —
    явно настроенная бесплатная доставка всегда. См. ADR-0002."""
    per_order_min_amount: float = 0.0
    lead_time_days: int = 0


class SupplierCreate(BaseModel):
    name: str
    contacts: str | None = None
    currency: str = "USD"
    delivery_policy: DeliveryPolicy = DeliveryPolicy()


class SupplierUpdate(BaseModel):
    """Частичное обновление (PATCH-семантика): поля, не переданные в payload,
    сохраняют текущее значение в БД, а не сбрасываются на дефолт. delivery_policy
    мержится по ключам, а не заменяется целиком — см. update_supplier."""

    name: str | None = None
    contacts: str | None = None
    currency: str | None = None
    delivery_policy: DeliveryPolicy | None = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    contacts: str | None
    currency: str
    delivery_policy: DeliveryPolicy
