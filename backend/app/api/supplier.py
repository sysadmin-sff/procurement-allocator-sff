import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.supplier import (
    OfficeCreate,
    OfficeOut,
    OfficeUpdate,
    SupplierContactCreate,
    SupplierContactOut,
    SupplierContactUpdate,
    SupplierCreate,
    SupplierDetailOut,
    SupplierOut,
    SupplierUpdate,
)
from app.auth.dependencies import require_role
from app.core.database import get_db
from app.models import Office, Supplier, SupplierContact
from app.supplier_directory.service import (
    OfficeMismatchError,
    OfficeNotFoundError,
    SupplierContactNotFoundError,
    create_contact,
    create_office,
    delete_contact,
    delete_office,
    update_contact,
    update_office,
)

router = APIRouter(prefix="/suppliers", dependencies=[Depends(require_role("admin"))])


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


@router.get("/{supplier_id}", response_model=SupplierDetailOut)
def get_supplier(supplier_id: uuid.UUID, db: Session = Depends(get_db)) -> SupplierDetailOut:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return SupplierDetailOut(
        **SupplierOut.model_validate(supplier).model_dump(),
        offices=[OfficeOut.model_validate(o) for o in supplier.offices],
        supplier_contacts=[
            SupplierContactOut.model_validate(c) for c in supplier.contacts_directory
        ],
    )


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


@router.post("/{supplier_id}/offices", response_model=OfficeOut, status_code=201)
def create_supplier_office(
    supplier_id: uuid.UUID, payload: OfficeCreate, db: Session = Depends(get_db)
) -> Office:
    if db.get(Supplier, supplier_id) is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return create_office(db, supplier_id, payload.address, payload.region)


@router.patch("/{supplier_id}/offices/{office_id}", response_model=OfficeOut)
def update_supplier_office(
    supplier_id: uuid.UUID,
    office_id: uuid.UUID,
    payload: OfficeUpdate,
    db: Session = Depends(get_db),
) -> Office:
    if db.get(Supplier, supplier_id) is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    try:
        return update_office(
            db,
            supplier_id,
            office_id,
            payload.address,
            payload.region,
            payload.model_fields_set,
        )
    except OfficeNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Office not found") from exc


@router.delete("/{supplier_id}/offices/{office_id}", status_code=204)
def delete_supplier_office(
    supplier_id: uuid.UUID, office_id: uuid.UUID, db: Session = Depends(get_db)
) -> None:
    if db.get(Supplier, supplier_id) is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    try:
        delete_office(db, supplier_id, office_id)
    except OfficeNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Office not found") from exc


@router.post("/{supplier_id}/contacts", response_model=SupplierContactOut, status_code=201)
def create_supplier_contact(
    supplier_id: uuid.UUID, payload: SupplierContactCreate, db: Session = Depends(get_db)
) -> SupplierContact:
    if db.get(Supplier, supplier_id) is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    try:
        return create_contact(
            db,
            supplier_id,
            payload.name,
            payload.role,
            payload.phone,
            payload.email,
            payload.office_id,
        )
    except OfficeMismatchError as exc:
        raise HTTPException(
            status_code=422, detail="Office does not belong to this supplier"
        ) from exc


@router.patch("/{supplier_id}/contacts/{contact_id}", response_model=SupplierContactOut)
def update_supplier_contact(
    supplier_id: uuid.UUID,
    contact_id: uuid.UUID,
    payload: SupplierContactUpdate,
    db: Session = Depends(get_db),
) -> SupplierContact:
    if db.get(Supplier, supplier_id) is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    try:
        return update_contact(
            db,
            supplier_id,
            contact_id,
            payload.name,
            payload.role,
            payload.phone,
            payload.email,
            payload.office_id,
            payload.model_fields_set,
        )
    except SupplierContactNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Contact not found") from exc
    except OfficeMismatchError as exc:
        raise HTTPException(
            status_code=422, detail="Office does not belong to this supplier"
        ) from exc


@router.delete("/{supplier_id}/contacts/{contact_id}", status_code=204)
def delete_supplier_contact(
    supplier_id: uuid.UUID, contact_id: uuid.UUID, db: Session = Depends(get_db)
) -> None:
    if db.get(Supplier, supplier_id) is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    try:
        delete_contact(db, supplier_id, contact_id)
    except SupplierContactNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Contact not found") from exc
