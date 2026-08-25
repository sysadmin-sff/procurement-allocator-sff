"""HTTP endpoints for price-list upload/review/apply — see ADR-0019 §5."""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.schemas.price_ingestion import (
    ApplyEntryIn,
    PriceListEntryOut,
    PriceListImportOut,
)
from app.core.database import get_db
from app.models import Material
from app.price_ingestion.apply import EntryNotFoundError, apply_price_list_entry
from app.price_ingestion.extraction import (
    PriceIngestionError,
    UnsupportedFileTypeError,
    validate_content_type,
)
from app.price_ingestion.service import (
    ImportNotFoundError,
    SupplierNotFoundError,
    create_price_list_import,
    get_price_list_import,
    maybe_mark_import_approved,
)

router = APIRouter()

MAX_PRICE_LIST_FILE_SIZE = 10 * 1024 * 1024


def _entry_out(
    entry, *, suggested_internal_sku=None, possible_duplicate_of=None
) -> PriceListEntryOut:
    return PriceListEntryOut(
        id=entry.id,
        supplier_raw_name=entry.supplier_raw_name,
        supplier_sku=entry.supplier_sku,
        matched_material_id=entry.matched_material_id,
        confidence=float(entry.confidence) if entry.confidence is not None else None,
        reasoning=entry.reasoning,
        price=float(entry.price),
        currency=entry.currency,
        availability=entry.availability,
        min_order_qty=entry.min_order_qty,
        action=entry.action,
        suggested_internal_sku=suggested_internal_sku,
        possible_duplicate_of=possible_duplicate_of or [],
    )


def _to_import_out(price_list_import) -> PriceListImportOut:
    """Plain DB-only rendering — used by GET, where suggested_internal_sku
    and possible_duplicate_of cannot be reconstructed (not persisted
    columns, see ADR-0019 §5 / docs/known-issues.md)."""
    return PriceListImportOut(
        import_id=price_list_import.id,
        status=price_list_import.status,
        entries=[_entry_out(e) for e in price_list_import.entries],
    )


def _to_import_out_with_matches(price_list_import) -> PriceListImportOut:
    """Upload-time rendering — enriches each entry with
    suggested_internal_sku / possible_duplicate_of from the in-memory
    MatchedLine list that produced it (converting batch indices to the
    actual persisted entry UUIDs). Only available right after creation;
    see create_price_list_import's `_matched_lines` note."""
    matched_lines = getattr(price_list_import, "_matched_lines", None)
    if matched_lines is None:
        return _to_import_out(price_list_import)

    entries_by_index = [entry for entry, _line in matched_lines]
    out_entries = []
    for entry, line in matched_lines:
        duplicate_uuids = [entries_by_index[i].id for i in line.possible_duplicate_of]
        out_entries.append(
            _entry_out(
                entry,
                suggested_internal_sku=line.decision.suggested_internal_sku,
                possible_duplicate_of=duplicate_uuids,
            )
        )

    return PriceListImportOut(
        import_id=price_list_import.id,
        status=price_list_import.status,
        entries=out_entries,
    )


@router.post(
    "/suppliers/{supplier_id}/price-lists",
    response_model=PriceListImportOut,
    status_code=201,
)
async def upload_price_list(
    supplier_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> PriceListImportOut:
    """Multipart upload of a supplier price list — see ADR-0019 §5. Runs
    extraction + matching synchronously and returns the full set of
    PriceListEntry for the review screen. The file itself is not
    persisted (same MVP choice as ADR-0018 §7); only its filename is kept
    as PriceListImport.file_ref."""
    try:
        validate_content_type(file.content_type)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=422,
            detail="Неподдерживаемый тип файла — загрузите PDF или изображение (PNG/JPEG/WEBP).",
        ) from exc

    file_bytes = await file.read()
    if len(file_bytes) > MAX_PRICE_LIST_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Файл слишком большой (максимум 10MB).")

    try:
        price_list_import = create_price_list_import(
            db,
            supplier_id,
            file_bytes=file_bytes,
            content_type=file.content_type or "",
            filename=file.filename or "price-list",
        )
    except SupplierNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Supplier not found") from exc
    except PriceIngestionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _to_import_out_with_matches(price_list_import)


@router.get("/price-list-imports/{import_id}", response_model=PriceListImportOut)
def get_price_list_import_endpoint(
    import_id: uuid.UUID, db: Session = Depends(get_db)
) -> PriceListImportOut:
    try:
        price_list_import = get_price_list_import(db, import_id)
    except ImportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Price list import not found") from exc
    return _to_import_out(price_list_import)


@router.post(
    "/price-list-imports/{import_id}/entries/{entry_id}/apply",
    response_model=PriceListEntryOut,
)
def apply_entry(
    import_id: uuid.UUID,
    entry_id: uuid.UUID,
    payload: ApplyEntryIn,
    db: Session = Depends(get_db),
) -> PriceListEntryOut:
    if payload.action == "match" and db.get(Material, payload.material_id) is None:
        raise HTTPException(status_code=404, detail="Material not found")

    try:
        entry = apply_price_list_entry(
            db,
            import_id,
            entry_id,
            action=payload.action,
            material_id=payload.material_id,
            internal_sku=payload.internal_sku,
            canonical_name=payload.canonical_name,
        )
    except EntryNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Price list entry not found") from exc

    maybe_mark_import_approved(db, import_id)
    db.refresh(entry)

    return _entry_out(entry)
