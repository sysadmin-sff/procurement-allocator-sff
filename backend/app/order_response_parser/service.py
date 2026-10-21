"""Grouping the OpenAI extraction result into matched/missing/extra — see
ADR-0018 §3. Read-only: this module never writes to OrderItem/PurchaseRecord,
it only builds the preview shown on screen before the employee confirms
(existing set_order_item_fields/create_purchase_record endpoints do the
actual writes — ADR-0007 §3, ADR-0013 §3, ADR-0008 §5).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Material, Order, OrderItem, SupplierMaterialAlias
from app.order_response_parser.client import (
    ExtractedLine,
    OrderResponseParsingError,
    UnsupportedFileTypeError,
    parse_order_response_document,
    validate_content_type,
)

__all__ = [
    "OrderResponseParsingError",
    "UnsupportedFileTypeError",
    "OrderNotFoundError",
    "MaterialNotFoundError",
    "AliasConflictError",
    "AliasNotFoundError",
    "parse_order_response",
    "validate_content_type",
    "create_response_alias",
    "delete_response_alias",
]

logger = logging.getLogger(__name__)

_ALIAS_REASONING_PREFIX = "[сопоставлено по сохранённому alias поставщика] "


def _normalize_for_alias_match(text: str) -> str:
    """Case- and whitespace-insensitive comparison key — the only
    normalization this ADR introduces, applied only here, in Python, over
    an already-loaded set of this supplier's order_response aliases. Does
    not change find_known_alias/price-ingestion's exact SQL comparison.
    See ADR-0046 §1 п.3."""
    return " ".join(text.split()).casefold()


def _apply_alias_post_match(
    db: Session, order: Order, extracted: list[ExtractedLine]
) -> set[uuid.UUID]:
    """Deterministic, code-level post-match over lines the model left
    unmatched (matched_order_item_id is None) — see ADR-0046 §1. Never
    overwrites a model match. Links a line to an OrderItem only when
    exactly one non-declined, not-yet-claimed OrderItem shares the
    alias's material_id — zero or multiple candidates is left alone
    (missing is the safe default, same principle as ADR-0044 §3's
    detect_mismatched_items). Mutates matching ExtractedLine objects in
    place (matched_order_item_id, reasoning — never confidence, see
    ADR-0046 §1 "Почему confidence не меняется"). Returns the set of
    OrderItem ids newly matched by this step, used both to build
    MatchedLineOut.matched_by_alias in the API layer and to log
    post_match_hits."""
    aliases = list(
        db.scalars(
            select(SupplierMaterialAlias).where(
                SupplierMaterialAlias.supplier_id == order.supplier_id,
                SupplierMaterialAlias.origin == "order_response",
            )
        )
    )
    aliases_by_normalized_name: dict[str, list[SupplierMaterialAlias]] = {}
    for alias in aliases:
        aliases_by_normalized_name.setdefault(
            _normalize_for_alias_match(alias.supplier_raw_name), []
        ).append(alias)

    claimed_item_ids = {
        line.matched_order_item_id for line in extracted if line.matched_order_item_id is not None
    }
    items_by_material_id: dict[uuid.UUID, list[OrderItem]] = {}
    for item in order.items:
        if item.declined_at is None and item.material_id is not None:
            items_by_material_id.setdefault(item.material_id, []).append(item)

    alias_matched_ids: set[uuid.UUID] = set()
    for line in extracted:
        if line.matched_order_item_id is not None:
            continue
        normalized = _normalize_for_alias_match(line.raw_description)
        candidates = aliases_by_normalized_name.get(normalized)
        if not candidates:
            continue
        # Multiple aliases normalizing to the same text (e.g. different
        # material_id) is as ambiguous as multiple OrderItem candidates —
        # only a single alias with a single eligible OrderItem counts.
        if len(candidates) != 1:
            continue
        material_id = candidates[0].material_id
        eligible_items = [
            item
            for item in items_by_material_id.get(material_id, [])
            if item.id not in claimed_item_ids
        ]
        if len(eligible_items) != 1:
            continue
        target = eligible_items[0]
        line.matched_order_item_id = target.id
        line.reasoning = _ALIAS_REASONING_PREFIX + line.reasoning
        claimed_item_ids.add(target.id)
        alias_matched_ids.add(target.id)

    return alias_matched_ids


class OrderNotFoundError(Exception):
    def __init__(self, order_id: uuid.UUID):
        self.order_id = order_id
        super().__init__(f"Order {order_id} not found")


def _order_items_context(order: Order) -> list[dict]:
    """Excludes declined+replaced items (declined_at IS NOT NULL) — they are
    no longer this supplier's to answer for, so they must not be offered to
    the LLM as matching candidates. See ADR-0043."""
    return [
        {
            "id": item.id,
            "canonical_name": (
                item.material.canonical_name if item.material_id else item.raw_description
            ),
            "quantity": item.quantity,
            "quoted_price": float(item.quoted_price),
        }
        for item in order.items
        if item.declined_at is None
    ]


def parse_order_response(
    db: Session,
    order_id: uuid.UUID,
    *,
    file_bytes: bytes,
    content_type: str,
) -> tuple[list[ExtractedLine], list[OrderItem], list[ExtractedLine], set[uuid.UUID]]:
    """Runs the single OpenAI call, links any still-unmatched line to a
    known SupplierMaterialAlias (post-match, ADR-0046 §1), then groups the
    result into three categories — see ADR-0018 §3:

    - matched: extracted lines with matched_order_item_id != null (all
      confidence levels, including "low" — ADR-0018 §3a/§6; this now
      includes lines the post-match step linked, not only the model).
    - missing: this Order's non-declined OrderItem that no extracted line
      referenced (declined_at IS NOT NULL items are excluded — ADR-0043,
      their absence from this supplier's reply is expected, not a gap).
    - extra: extracted lines with matched_order_item_id == null.

    Returns (matched_lines, missing_items, extra_lines,
    alias_matched_order_item_ids) — the fourth element is the set of
    OrderItem ids the post-match step (not the model) linked this call,
    used by the API layer to set MatchedLineOut.matched_by_alias. Never
    writes to the database — pure read + OpenAI call. Raises
    OrderNotFoundError, UnsupportedFileTypeError (validated before any
    OpenAI call is made), or OrderResponseParsingError (OpenAI failure).
    """
    validate_content_type(content_type)

    order = db.get(Order, order_id)
    if order is None:
        raise OrderNotFoundError(order_id)

    order_items = _order_items_context(order)
    extracted = parse_order_response_document(
        file_bytes=file_bytes,
        content_type=content_type,
        order_items=order_items,
    )

    aliases_loaded = db.scalar(
        select(sa_func.count())
        .select_from(SupplierMaterialAlias)
        .where(
            SupplierMaterialAlias.supplier_id == order.supplier_id,
            SupplierMaterialAlias.origin == "order_response",
        )
    )
    extra_lines_before = sum(1 for line in extracted if line.matched_order_item_id is None)

    alias_matched_ids = _apply_alias_post_match(db, order, extracted)

    logger.info(
        "order_response_post_match",
        extra={
            "order_id": str(order_id),
            "aliases_loaded": aliases_loaded,
            "extra_lines_before": extra_lines_before,
            "post_match_hits": len(alias_matched_ids),
        },
    )

    matched_ids = {line.matched_order_item_id for line in extracted if line.matched_order_item_id}

    matched_lines = [line for line in extracted if line.matched_order_item_id is not None]
    extra_lines = [line for line in extracted if line.matched_order_item_id is None]
    missing_items = [
        item for item in order.items if item.declined_at is None and item.id not in matched_ids
    ]

    return matched_lines, missing_items, extra_lines, alias_matched_ids


class MaterialNotFoundError(Exception):
    def __init__(self, material_id: uuid.UUID):
        self.material_id = material_id
        super().__init__(f"Material {material_id} not found")


class AliasConflictError(Exception):
    """Raised when (supplier_id, supplier_raw_name, origin='order_response')
    already exists with a DIFFERENT material_id and the caller did not
    pass force=True — see ADR-0046 §2. Carries the existing alias so the
    API layer can build the 409 body."""

    def __init__(self, existing: SupplierMaterialAlias):
        self.existing = existing
        super().__init__("Alias already exists with a different material_id")


class AliasNotFoundError(Exception):
    def __init__(self, alias_id: uuid.UUID):
        self.alias_id = alias_id
        super().__init__(f"SupplierMaterialAlias {alias_id} not found")


def create_response_alias(
    db: Session,
    order_id: uuid.UUID,
    *,
    supplier_raw_name: str,
    supplier_sku: str | None,
    material_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    force: bool = False,
) -> SupplierMaterialAlias:
    """Creates (or, with force=True, overwrites) an order_response-origin
    alias from the "Связать" button — see ADR-0046 §2. Exact-match
    comparison on supplier_raw_name for conflict/idempotency, not the
    normalized comparison the post-match read path uses (ADR-0046 §2: an
    intentional asymmetry — writing stays exact so price-ingestion's
    _upsert_alias/uniqueness semantics don't need to change alongside
    this). Raises OrderNotFoundError, MaterialNotFoundError, or
    AliasConflictError (when a different material_id is already stored for
    this exact (supplier_id, supplier_raw_name) and force is not set)."""
    order = db.get(Order, order_id)
    if order is None:
        raise OrderNotFoundError(order_id)

    material = db.get(Material, material_id)
    if material is None:
        raise MaterialNotFoundError(material_id)

    existing = db.scalar(
        select(SupplierMaterialAlias).where(
            SupplierMaterialAlias.supplier_id == order.supplier_id,
            SupplierMaterialAlias.supplier_raw_name == supplier_raw_name,
            SupplierMaterialAlias.origin == "order_response",
        )
    )

    if existing is not None and existing.material_id == material_id:
        return existing  # exact triple already present — idempotent no-op

    if existing is not None and not force:
        raise AliasConflictError(existing)

    if existing is not None and force:
        existing.material_id = material_id
        existing.supplier_sku = supplier_sku
        existing.created_by_user_id = created_by_user_id
        existing.created_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        return existing

    alias = SupplierMaterialAlias(
        supplier_id=order.supplier_id,
        material_id=material_id,
        supplier_sku=supplier_sku,
        supplier_raw_name=supplier_raw_name,
        origin="order_response",
        created_by_user_id=created_by_user_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return alias


def delete_response_alias(db: Session, supplier_id: uuid.UUID, alias_id: uuid.UUID) -> None:
    """Deletes an origin='order_response' alias by id, scoped to
    supplier_id — see ADR-0046 §2/§5/§6. This endpoint exists to undo a
    mistaken "Связать" click, not to manage price-ingestion's vocabulary
    — a price_import-origin alias is treated the same as a wrong
    supplier_id: AliasNotFoundError, not deleted. (The SQL recipe in
    ADR-0046 §6/known-issues.md is the only path for removing a
    price_import alias.) Raises AliasNotFoundError if alias_id doesn't
    exist, belongs to a different supplier_id than the one in the path,
    or has origin='price_import' — same "don't reveal another resource's
    existence" principle as the rest of order.py's 404s."""
    alias = db.get(SupplierMaterialAlias, alias_id)
    if alias is None or alias.supplier_id != supplier_id or alias.origin != "order_response":
        raise AliasNotFoundError(alias_id)
    db.delete(alias)
    db.commit()
