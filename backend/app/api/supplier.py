import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.supplier import SupplierCreate, SupplierOut, SupplierUpdate
from app.core.database import get_db
from app.models import Supplier

router = APIRouter(prefix="/suppliers")


@router.post("", response_model=SupplierOut, status_code=201)
def create_supplier(payload: SupplierCreate, db: Session = Depends(get_db)) -> Supplier:
    supplier = Supplier(
        name=payload.name,
        contacts=payload.contacts,
        currency=payload.currency,
        delivery_policy=payload.delivery_policy.model_dump(),
    )
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


@router.get("", response_model=list[SupplierOut])
def list_suppliers(db: Session = Depends(get_db)) -> list[Supplier]:
    return list(db.query(Supplier).order_by(Supplier.name).all())


@router.get("/{supplier_id}", response_model=SupplierOut)
def get_supplier(supplier_id: uuid.UUID, db: Session = Depends(get_db)) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


@router.put("/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: uuid.UUID, payload: SupplierUpdate, db: Session = Depends(get_db)
) -> Supplier:
    """PATCH-семантика: поля, отсутствующие в payload, не трогаются.
    delivery_policy мержится по ключам, а не заменяется целиком, чтобы частичный
    payload не обнулял ранее настроенные flat_fee/free_shipping_threshold/etc."""
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")

    fields = payload.model_dump(exclude_unset=True)
    if "delivery_policy" in fields:
        supplier.delivery_policy = {
            **supplier.delivery_policy,
            **fields.pop("delivery_policy"),
        }
    for field_name, value in fields.items():
        setattr(supplier, field_name, value)

    db.commit()
    db.refresh(supplier)
    return supplier


@router.delete("/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    db.delete(supplier)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Supplier is referenced by other records"
        ) from exc
