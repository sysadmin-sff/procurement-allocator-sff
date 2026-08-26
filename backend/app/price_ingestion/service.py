"""Orchestration for price-list upload — see ADR-0019 §5, ADR-0025 §5.
Ties extraction (step 1) + matching (step 2) together, creates
PriceListImport and its PriceListEntry rows, and answers "is this import
fully resolved" for the apply endpoint to decide when to flip status to
"approved". Lines the matcher decided action="not_found" on are not
persisted as PriceListEntry at all — see ADR-0025 §5, an accepted risk:
the review screen never shows them, so a persisted-but-invisible row
would be dead data (same argument ADR-0025 §4 applies to the removed
suggested_internal_sku column).
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

    # action="not_found" lines are not persisted as PriceListEntry at all
    # — see ADR-0025 §5. A "failed" line (ADR-0022 §2 retry exhaustion)
    # carries a placeholder action="not_found" decision too, but it is not
    # a real not_found decision — it still becomes a visible entry, same
    # as before this ADR, so the review screen can surface the failure.
    entries_by_index: dict[int, PriceListEntry] = {}
    for i, line in enumerate(matched):
        failed = line.processing_status == "failed"
        if line.decision.action == "not_found" and not failed:
            continue

        entry = PriceListEntry(
            import_id=price_list_import.id,
            supplier_raw_name=line.extracted.raw_name,
            supplier_sku=line.extracted.raw_sku,
            matched_material_id=(
                None
                if failed
                else (line.decision.material_id if line.decision.action == "match" else None)
            ),
            confidence=None if failed else line.decision.confidence,
            reasoning=None if failed else line.decision.reasoning,
            price=line.extracted.price,
            currency=line.extracted.currency,
            availability=line.extracted.availability,
            min_order_qty=line.extracted.min_order_qty,
            action=None,
            processing_status=line.processing_status,
        )
        db.add(entry)
        entries_by_index[i] = entry

    db.flush()

    # possible_duplicate_of references other PriceListEntry from this same
    # batch by id — entries must be flushed (have ids) before it can be
    # written. MatchedLine.possible_duplicate_of holds batch indices, not
    # ids (see matching.py), translated to real entry ids here, once, at
    # write time — see ADR-0020 (supersedes ADR-0019 §5's transient
    # in-memory approach, which lost this data on any GET after the
    # initial upload response). An index pointing at a filtered-out
    # not_found line (dropped above) is skipped — nothing to reference.
    for i, entry in entries_by_index.items():
        line = matched[i]
        if line.possible_duplicate_of:
            entry.possible_duplicate_of = [
                str(entries_by_index[j].id)
                for j in line.possible_duplicate_of
                if j in entries_by_index
            ] or None

    db.commit()
    db.refresh(price_list_import)

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
