"""Pydantic-схемы для CRUD /suppliers.

delivery_policy типизирован явной подсхемой (а не сырым dict), чтобы API
валидировал форму на входе — поля соответствуют ADR-0002 (flat_fee,
free_shipping_threshold, per_order_min_amount, lead_time_days).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


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
    short_name: str | None = None
    contacts: str | None = None
    currency: str | None = None
    delivery_policy: DeliveryPolicy | None = None
    website: str | None = None
    region: str | None = None
    catalog_link: str | None = None
    status: str | None = None
    payment_terms: str | None = None
    portal_url: str | None = None
    comments: str | None = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    short_name: str | None
    contacts: str | None
    currency: str
    delivery_policy: DeliveryPolicy
    website: str | None
    region: str | None
    catalog_link: str | None
    status: str | None
    payment_terms: str | None
    portal_url: str | None
    comments: str | None


class OfficeCreate(BaseModel):
    address: str = Field(min_length=1)
    region: str | None = None


class OfficeUpdate(BaseModel):
    """Частичное обновление — та же PATCH-семантика, что у SupplierUpdate."""

    address: str | None = Field(default=None, min_length=1)
    region: str | None = None


class OfficeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    supplier_id: uuid.UUID
    address: str
    region: str | None


class SupplierContactCreate(BaseModel):
    name: str = Field(min_length=1)
    role: str | None = None
    phone: str | None = None
    email: str | None = None
    office_id: uuid.UUID | None = None


class SupplierContactUpdate(BaseModel):
    """Частичное обновление — та же PATCH-семантика, что у SupplierUpdate."""

    name: str | None = Field(default=None, min_length=1)
    role: str | None = None
    phone: str | None = None
    email: str | None = None
    office_id: uuid.UUID | None = None


class SupplierContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    supplier_id: uuid.UUID
    office_id: uuid.UUID | None
    name: str
    role: str | None
    phone: str | None
    email: str | None


class SupplierDetailOut(SupplierOut):
    """contacts (унаследовано от SupplierOut) — существующее свободнотекстовое
    поле, не трогается. Структурированный список — отдельное имя, чтобы не
    затенять его, см. ADR-0010 п.5."""

    offices: list[OfficeOut]
    supplier_contacts: list[SupplierContactOut]
