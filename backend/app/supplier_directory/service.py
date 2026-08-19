"""Office and SupplierContact CRUD nested under a Supplier — see ADR-0010.

Office deletion sets office_id to NULL on any contacts pointed at it (DB-level
ON DELETE SET NULL, mirrored by expiring the in-session objects here) rather
than RESTRICT: ADR-0010 п.2 treats office_id as genuinely optional — contacts
without a clear single-office attribution are a normal case ("General email,
they accept orders"), so an office going away should not force deleting or
blocking on the contacts that referenced it.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Office, SupplierContact


class OfficeNotFoundError(Exception):
    def __init__(self, supplier_id: uuid.UUID, office_id: uuid.UUID):
        self.supplier_id = supplier_id
        self.office_id = office_id
        super().__init__(f"Office {office_id} not found for supplier {supplier_id}")


class SupplierContactNotFoundError(Exception):
    def __init__(self, supplier_id: uuid.UUID, contact_id: uuid.UUID):
        self.supplier_id = supplier_id
        self.contact_id = contact_id
        super().__init__(f"SupplierContact {contact_id} not found for supplier {supplier_id}")


class OfficeMismatchError(Exception):
    """Raised when a contact's office_id points at an office belonging to a
    different supplier — see ADR-0010 п.3 (contact/office endpoints)."""

    def __init__(self, supplier_id: uuid.UUID, office_id: uuid.UUID):
        self.supplier_id = supplier_id
        self.office_id = office_id
        super().__init__(f"Office {office_id} does not belong to supplier {supplier_id}")


def _get_office_or_raise(db: Session, supplier_id: uuid.UUID, office_id: uuid.UUID) -> Office:
    office = db.get(Office, office_id)
    if office is None or office.supplier_id != supplier_id:
        raise OfficeNotFoundError(supplier_id, office_id)
    return office


def _get_contact_or_raise(
    db: Session, supplier_id: uuid.UUID, contact_id: uuid.UUID
) -> SupplierContact:
    contact = db.get(SupplierContact, contact_id)
    if contact is None or contact.supplier_id != supplier_id:
        raise SupplierContactNotFoundError(supplier_id, contact_id)
    return contact


def _check_office_belongs_to_supplier(
    db: Session, supplier_id: uuid.UUID, office_id: uuid.UUID | None
) -> None:
    if office_id is None:
        return
    office = db.get(Office, office_id)
    if office is None or office.supplier_id != supplier_id:
        raise OfficeMismatchError(supplier_id, office_id)


def create_office(
    db: Session, supplier_id: uuid.UUID, address: str, region: str | None
) -> Office:
    office = Office(supplier_id=supplier_id, address=address, region=region)
    db.add(office)
    db.commit()
    db.refresh(office)
    return office


def update_office(
    db: Session,
    supplier_id: uuid.UUID,
    office_id: uuid.UUID,
    address: str | None,
    region: str | None,
    fields_set: set[str],
) -> Office:
    office = _get_office_or_raise(db, supplier_id, office_id)
    if "address" in fields_set and address is not None:
        office.address = address
    if "region" in fields_set:
        office.region = region
    db.commit()
    db.refresh(office)
    return office


def delete_office(db: Session, supplier_id: uuid.UUID, office_id: uuid.UUID) -> None:
    office = _get_office_or_raise(db, supplier_id, office_id)
    contacts = db.query(SupplierContact).filter(SupplierContact.office_id == office_id).all()
    db.delete(office)
    db.commit()
    for contact in contacts:
        db.refresh(contact)


def create_contact(
    db: Session,
    supplier_id: uuid.UUID,
    name: str,
    role: str | None,
    phone: str | None,
    email: str | None,
    office_id: uuid.UUID | None,
) -> SupplierContact:
    _check_office_belongs_to_supplier(db, supplier_id, office_id)
    contact = SupplierContact(
        supplier_id=supplier_id,
        office_id=office_id,
        name=name,
        role=role,
        phone=phone,
        email=email,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def update_contact(
    db: Session,
    supplier_id: uuid.UUID,
    contact_id: uuid.UUID,
    name: str | None,
    role: str | None,
    phone: str | None,
    email: str | None,
    office_id: uuid.UUID | None,
    fields_set: set[str],
) -> SupplierContact:
    contact = _get_contact_or_raise(db, supplier_id, contact_id)
    if "office_id" in fields_set:
        _check_office_belongs_to_supplier(db, supplier_id, office_id)
        contact.office_id = office_id
    if "name" in fields_set and name is not None:
        contact.name = name
    if "role" in fields_set:
        contact.role = role
    if "phone" in fields_set:
        contact.phone = phone
    if "email" in fields_set:
        contact.email = email
    db.commit()
    db.refresh(contact)
    return contact


def delete_contact(db: Session, supplier_id: uuid.UUID, contact_id: uuid.UUID) -> None:
    contact = _get_contact_or_raise(db, supplier_id, contact_id)
    db.delete(contact)
    db.commit()
