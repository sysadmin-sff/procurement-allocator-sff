"""Orchestration for price-list upload — see ADR-0019 §5. Ties extraction
(step 1) + matching (step 2) together, creates PriceListImport and its
PriceListEntry rows, and answers "is this import fully resolved" for the
apply endpoint to decide when to flip status to "approved".
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy.orm import Session

from app.models import PriceListEntry, PriceListImport, Supplier
from app.price_ingestion.extraction import extract_price_list_lines
from app.price_ingestion.matching import match_price_list_lines

__all__ = [
    "ImportNotFoundError",
    "SupplierNotFoundError",
    "create_price_list_import",
    "get_price_list_import",
    "maybe_mark_import_approved",
]


class SupplierNotFoundError(Exception):
    def __init__(self, supplier_id: uuid.UUID):
        self.supplier_id = supplier_id
        super().__init__(f"Supplier {supplier_id} not found")


class ImportNotFoundError(Exception):
    def __init__(self, import_id: uuid.UUID):
        self.import_id = import_id
        super().__init__(f"PriceListImport {import_id} not found")


def create_price_list_import(
    db: Session,
    supplier_id: uuid.UUID,
    *,
    file_bytes: bytes,
    content_type: str,
    filename: str,
) -> PriceListImport:
    """Runs extraction + matching and persists one PriceListEntry per
    extracted line — see ADR-0019 §5. file_ref stores only the filename
    (the file itself is not persisted, same MVP choice as ADR-0018 §7)."""
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise SupplierNotFoundError(supplier_id)

    extracted = extract_price_list_lines(file_bytes=file_bytes, content_type=content_type)
    matched = match_price_list_lines(db, supplier_id, extracted)

    price_list_import = PriceListImport(
        supplier_id=supplier_id,
        file_ref=filename,
        uploaded_at=datetime.datetime.now(datetime.timezone.utc),
        status="pending_review",
        parsed_by_ai_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(price_list_import)
    db.flush()

    entries: list[PriceListEntry] = []
    for line in matched:
        entry = PriceListEntry(
            import_id=price_list_import.id,
            supplier_raw_name=line.extracted.raw_name,
            supplier_sku=line.extracted.raw_sku,
            matched_material_id=(
                line.decision.material_id if line.decision.action == "match" else None
            ),
            confidence=line.decision.confidence,
            reasoning=line.decision.reasoning,
            price=line.extracted.price,
            currency=line.extracted.currency,
            availability=line.extracted.availability,
            min_order_qty=line.extracted.min_order_qty,
            action=None,
        )
        db.add(entry)
        entries.append(entry)

    db.commit()
    db.refresh(price_list_import)

    # suggested_internal_sku / possible_duplicate_of are not columns on
    # PriceListEntry (schema frozen — see Global Constraints), so they can
    # only be surfaced right here, from the in-memory MatchedLine list that
    # produced these rows. Stashed as a transient (non-persisted) attribute
    # for the endpoint layer to zip with price_list_import.entries; a later
    # GET re-reads from the DB alone and cannot reconstruct these two
    # fields — accepted MVP gap, see docs/known-issues.md (ADR-0019 §5).
    price_list_import._matched_lines = list(zip(entries, matched, strict=True))  # type: ignore[attr-defined]

    return price_list_import


def get_price_list_import(db: Session, import_id: uuid.UUID) -> PriceListImport:
    price_list_import = db.get(PriceListImport, import_id)
    if price_list_import is None:
        raise ImportNotFoundError(import_id)
    return price_list_import


def maybe_mark_import_approved(db: Session, import_id: uuid.UUID) -> None:
    """Flips PriceListImport.status to "approved" once every entry has an
    explicit action (match/new/skip) — see ADR-0019 §5. Stays
    pending_review while any entry.action is still NULL."""
    price_list_import = get_price_list_import(db, import_id)
    unresolved = (
        db.query(PriceListEntry)
        .filter(PriceListEntry.import_id == import_id, PriceListEntry.action.is_(None))
        .count()
    )
    if unresolved == 0:
        price_list_import.status = "approved"
        db.commit()
