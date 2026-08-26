"""PurchaseRecord CRUD and plan/fact total aggregation — see ADR-0008.

PurchaseRecord is a project-level, free-text journal of what was actually
bought, independent of Order/AllocationLine (ADR-0008 п.1-2): raw_description
need not match any Material, supplier_id need not match the Order the line
was originally planned under, and there is no requirement that a supplier
have an Order in this project at all (ADR-0008 п.2, "с колёс" case).

Aggregation (ADR-0008 п.4) compares purchased totals against Order.total_amount
— a snapshot of what was actually sent to the supplier — not against the live
SupplierAllocationSummaryOut, which can drift after ADR-0006 overrides made
after the Order was already sent. If a project/supplier has no Order at all,
there is no basis for a delta: None, not 0 (same "no data ≠ zero" rule as
price_delta in ADR-0007 п.4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, PurchaseRecord


class PurchaseRecordNotFoundError(Exception):
    def __init__(self, project_id: uuid.UUID, record_id: uuid.UUID):
        self.project_id = project_id
        self.record_id = record_id
        super().__init__(f"PurchaseRecord {record_id} not found in project {project_id}")


@dataclass
class TotalComparison:
    purchased_total: float
    planned_total: float | None
    delta: float | None
    delta_pct: float | None


def _compare(purchased_total: float, planned_total: float | None) -> TotalComparison:
    if planned_total is None:
        return TotalComparison(purchased_total, None, None, None)
    delta = purchased_total - planned_total
    delta_pct = (delta / planned_total * 100) if planned_total != 0 else 0.0
    return TotalComparison(purchased_total, planned_total, delta, delta_pct)


def get_project_totals(db: Session, project_id: uuid.UUID) -> TotalComparison:
    """purchased_total[project] vs sum of Order.total_amount for the whole
    project. planned_total is None (not 0) if the project has no Order yet
    — see module docstring / ADR-0008 п.4."""
    records = db.scalars(
        select(PurchaseRecord).where(PurchaseRecord.project_id == project_id)
    ).all()
    purchased_total = sum(float(r.quantity) * float(r.unit_price) for r in records)

    orders = db.scalars(select(Order).where(Order.project_id == project_id)).all()
    planned_total = sum(float(o.total_amount) for o in orders) if orders else None

    return _compare(purchased_total, planned_total)


def get_supplier_totals(
    db: Session, project_id: uuid.UUID
) -> dict[uuid.UUID, TotalComparison]:
    """purchased_total[project][supplier] vs sum of Order.total_amount for
    that supplier's Order(s) in this project (summed — a supplier can have
    more than one Order per project, e.g. a reorder, ADR-0007 п.2). Includes
    every supplier that has either a PurchaseRecord or an Order in this
    project, so an unplanned "с колёс" supplier (records but no Order) still
    shows up with planned_total=None, and a planned supplier with no actual
    purchase yet shows up with purchased_total=0."""
    records = db.scalars(
        select(PurchaseRecord).where(PurchaseRecord.project_id == project_id)
    ).all()
    orders = db.scalars(select(Order).where(Order.project_id == project_id)).all()

    purchased_by_supplier: dict[uuid.UUID, float] = {}
    for r in records:
        purchased_by_supplier[r.supplier_id] = purchased_by_supplier.get(
            r.supplier_id, 0.0
        ) + float(r.quantity) * float(r.unit_price)

    planned_by_supplier: dict[uuid.UUID, float] = {}
    for o in orders:
        planned_by_supplier[o.supplier_id] = planned_by_supplier.get(
            o.supplier_id, 0.0
        ) + float(o.total_amount)

    supplier_ids = set(purchased_by_supplier) | set(planned_by_supplier)
    return {
        supplier_id: _compare(
            purchased_by_supplier.get(supplier_id, 0.0),
            planned_by_supplier.get(supplier_id),
        )
        for supplier_id in supplier_ids
    }


def create_purchase_record(
    db: Session,
    project_id: uuid.UUID,
    supplier_id: uuid.UUID,
    raw_description: str,
    quantity: int,
    unit_price: float,
    material_id: uuid.UUID | None,
    created_by_user_id: uuid.UUID | None = None,
) -> PurchaseRecord:
    record = PurchaseRecord(
        project_id=project_id,
        supplier_id=supplier_id,
        raw_description=raw_description,
        quantity=quantity,
        unit_price=unit_price,
        material_id=material_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _get_record_or_raise(
    db: Session, project_id: uuid.UUID, record_id: uuid.UUID
) -> PurchaseRecord:
    record = db.get(PurchaseRecord, record_id)
    if record is None or record.project_id != project_id:
        raise PurchaseRecordNotFoundError(project_id, record_id)
    return record


def update_purchase_record(
    db: Session,
    project_id: uuid.UUID,
    record_id: uuid.UUID,
    supplier_id: uuid.UUID,
    raw_description: str,
    quantity: int,
    unit_price: float,
    material_id: uuid.UUID | None,
) -> PurchaseRecord:
    record = _get_record_or_raise(db, project_id, record_id)
    record.supplier_id = supplier_id
    record.raw_description = raw_description
    record.quantity = quantity
    record.unit_price = unit_price
    record.material_id = material_id
    db.commit()
    db.refresh(record)
    return record


def delete_purchase_record(
    db: Session, project_id: uuid.UUID, record_id: uuid.UUID
) -> None:
    record = _get_record_or_raise(db, project_id, record_id)
    db.delete(record)
    db.commit()
