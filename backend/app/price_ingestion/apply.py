"""Applying one reviewed PriceListEntry — see ADR-0019 §5. Each call is one
transaction: match closes the old active Price (if any) and upserts
SupplierMaterialAlias; new creates Material+Alias+Price together, rolling
back all three on any failure.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.models import Material, Price, PriceListEntry, SupplierMaterialAlias
from app.price_ingestion.embeddings import EmbeddingError, embed_text, material_embedding_input


class EntryNotFoundError(Exception):
    def __init__(self, import_id: uuid.UUID, entry_id: uuid.UUID):
        self.import_id = import_id
        self.entry_id = entry_id
        super().__init__(f"PriceListEntry {entry_id} not found in import {import_id}")


def _get_entry_or_raise(
    db: Session, import_id: uuid.UUID, entry_id: uuid.UUID
) -> PriceListEntry:
    entry = db.get(PriceListEntry, entry_id)
    if entry is None or entry.import_id != import_id:
        raise EntryNotFoundError(import_id, entry_id)
    return entry


def _upsert_alias(
    db: Session, supplier_id: uuid.UUID, material_id: uuid.UUID, raw_name: str
) -> None:
    existing = (
        db.query(SupplierMaterialAlias)
        .filter_by(supplier_id=supplier_id, material_id=material_id, supplier_raw_name=raw_name)
        .first()
    )
    if existing is None:
        db.add(
            SupplierMaterialAlias(
                supplier_id=supplier_id,
                material_id=material_id,
                supplier_raw_name=raw_name,
            )
        )


def _apply_match(
    db: Session, entry: PriceListEntry, supplier_id: uuid.UUID, material_id: uuid.UUID
) -> None:
    active_price = (
        db.query(Price)
        .filter(
            Price.material_id == material_id,
            Price.supplier_id == supplier_id,
            Price.valid_to.is_(None),
        )
        .first()
    )
    if active_price is not None:
        active_price.valid_to = datetime.date.today()

    new_price = Price(
        material_id=material_id,
        supplier_id=supplier_id,
        price=entry.price,
        currency=entry.currency,
        availability=entry.availability,
        min_order_qty=entry.min_order_qty,
        valid_from=datetime.date.today(),
        valid_to=None,
        source_import_id=entry.import_id,
    )
    db.add(new_price)
    _upsert_alias(db, supplier_id, material_id, entry.supplier_raw_name)

    entry.matched_material_id = material_id
    entry.action = "match"
    db.commit()


def _apply_new(
    db: Session,
    entry: PriceListEntry,
    supplier_id: uuid.UUID,
    internal_sku: str,
    canonical_name: str,
) -> None:
    material = Material(
        internal_sku=internal_sku,
        canonical_name=canonical_name,
        unit="unit",
        attributes={},
    )
    try:
        material.embedding = embed_text(material_embedding_input(canonical_name, {}))
    except EmbeddingError:
        material.embedding = None

    db.add(material)
    db.flush()

    _upsert_alias(db, supplier_id, material.id, entry.supplier_raw_name)

    price = Price(
        material_id=material.id,
        supplier_id=supplier_id,
        price=entry.price,
        currency=entry.currency,
        availability=entry.availability,
        min_order_qty=entry.min_order_qty,
        valid_from=datetime.date.today(),
        valid_to=None,
        source_import_id=entry.import_id,
    )
    db.add(price)

    entry.matched_material_id = material.id
    entry.action = "new"
    db.commit()


def apply_price_list_entry(
    db: Session,
    import_id: uuid.UUID,
    entry_id: uuid.UUID,
    *,
    action: Literal["match", "new", "skip"],
    material_id: uuid.UUID | None = None,
    internal_sku: str | None = None,
    canonical_name: str | None = None,
) -> PriceListEntry:
    """Applies one reviewed entry — see ADR-0019 §5. Raises EntryNotFoundError
    if the entry doesn't belong to this import. Any DB failure during
    action="new" rolls back Material+Alias+Price together (single
    transaction — no partial Material without its Price/Alias)."""
    entry = _get_entry_or_raise(db, import_id, entry_id)
    supplier_id = entry.import_.supplier_id

    if action == "skip":
        entry.action = "skip"
        db.commit()
        return entry

    try:
        if action == "match":
            assert material_id is not None
            _apply_match(db, entry, supplier_id, material_id)
        else:
            assert internal_sku is not None and canonical_name is not None
            _apply_new(db, entry, supplier_id, internal_sku, canonical_name)
    except Exception:
        db.rollback()
        raise

    db.refresh(entry)
    return entry
