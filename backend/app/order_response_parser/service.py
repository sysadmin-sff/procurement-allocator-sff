"""Grouping the OpenAI extraction result into matched/missing/extra — see
ADR-0018 §3. Read-only: this module never writes to OrderItem/PurchaseRecord,
it only builds the preview shown on screen before the employee confirms
(existing set_order_item_fields/create_purchase_record endpoints do the
actual writes — ADR-0007 §3, ADR-0013 §3, ADR-0008 §5).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Order, OrderItem
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
    "parse_order_response",
    "validate_content_type",
]


class OrderNotFoundError(Exception):
    def __init__(self, order_id: uuid.UUID):
        self.order_id = order_id
        super().__init__(f"Order {order_id} not found")


def _order_items_context(order: Order) -> list[dict]:
    return [
        {
            "id": item.id,
            "canonical_name": item.material.canonical_name,
            "quantity": item.quantity,
            "quoted_price": float(item.quoted_price),
        }
        for item in order.items
    ]


def parse_order_response(
    db: Session,
    order_id: uuid.UUID,
    *,
    file_bytes: bytes,
    content_type: str,
) -> tuple[list[ExtractedLine], list[OrderItem], list[ExtractedLine]]:
    """Runs the single OpenAI call and groups its output into three
    categories — see ADR-0018 §3:

    - matched: extracted lines with matched_order_item_id != null (all
      confidence levels, including "low" — ADR-0018 §3a/§6).
    - missing: this Order's OrderItem that no extracted line referenced.
    - extra: extracted lines with matched_order_item_id == null.

    Returns (matched_lines, missing_items, extra_lines). Never writes to the
    database — pure read + OpenAI call. Raises OrderNotFoundError,
    UnsupportedFileTypeError (validated before any OpenAI call is made), or
    OrderResponseParsingError (OpenAI failure).
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

    matched_ids = {line.matched_order_item_id for line in extracted if line.matched_order_item_id}

    matched_lines = [line for line in extracted if line.matched_order_item_id is not None]
    extra_lines = [line for line in extracted if line.matched_order_item_id is None]
    missing_items = [item for item in order.items if item.id not in matched_ids]

    return matched_lines, missing_items, extra_lines
