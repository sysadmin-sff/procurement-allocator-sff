"""Order-response pipeline accuracy validation — see ADR-0044 §2-4.

Ground truth comes from already-confirmed Order/OrderItem rows in the prod
DB (received_quantity/confirmed_price IS NOT NULL) — ADR-0013/ADR-0039.
The supplier-response documents themselves are never stored by the app
(Order.file_ref is a filename only, ADR-0018 §7), so the caller supplies a
mapping file pairing each document they already have on hand with the
Order it answers — see ADR-0044 §2 for why this is explicit, not guessed.

READ-ONLY: this script only reads the prod DB (db.get/db.scalars, via
parse_order_response_document below). session.commit() is never called
anywhere in this file — if it ever is, that is a deliberate break of this
script's read-only invariant, see ADR-0044 §2.

Usage (run on prod via the backend container, same mechanism as past prod
operations — see docs/known-issues.md):
    docker compose exec backend python -m app.scripts.validation.validate_order_response \\
        --mapping mapping.json --documents-dir ./docs --out ./report

mapping.json: [{"filename": "...", "order_id": "..."}, ...]
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Order
from app.order_response_parser.client import parse_order_response_document
from app.scripts.validation.csv_report import (
    order_response_csv_rows,
    order_response_markdown_report,
)
from app.scripts.validation.scoring import (
    OrderItemGroundTruth,
    OrderResponseScore,
    aggregate_order_response_scores,
    detect_mismatched_items,
    score_order_response_item,
)

_CONTENT_TYPE_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _content_type_for(path: Path) -> str:
    content_type = _CONTENT_TYPE_BY_SUFFIX.get(path.suffix.lower())
    if content_type is None:
        raise ValueError(f"Unsupported file extension: {path.suffix}")
    return content_type


def load_mapping(mapping_path: Path) -> list[tuple[str, uuid.UUID]]:
    """Parses the user-supplied document-to-Order mapping file — see
    module docstring and ADR-0044 §2. No content-based inference: the
    mapping is taken as given, exactly as the user wrote it."""
    entries = json.loads(mapping_path.read_text(encoding="utf-8"))
    return [(entry["filename"], uuid.UUID(entry["order_id"])) for entry in entries]


def score_order(
    db: Session, order_id: uuid.UUID, file_bytes: bytes, content_type: str
) -> list[OrderResponseScore]:
    """Scores every OrderItem on this Order that carries ground truth
    (received_quantity or confirmed_price not null) — see ADR-0044 §3.
    Read-only: only db.get is used, no writes."""
    order = db.get(Order, order_id)
    if order is None:
        print(f"Order {order_id} not found — skipping", file=sys.stderr)
        return []

    items_with_ground_truth = [
        item
        for item in order.items
        if item.declined_at is None
        and (item.received_quantity is not None or item.confirmed_price is not None)
    ]
    if not items_with_ground_truth:
        print(
            f"Order {order_id} has no OrderItem with confirmed ground truth — skipping",
            file=sys.stderr,
        )
        return []

    order_items_context = [
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
    extracted_lines = parse_order_response_document(
        file_bytes=file_bytes,
        content_type=content_type,
        order_items=order_items_context,
    )

    ground_truths = [
        OrderItemGroundTruth(
            order_item_id=item.id,
            received_quantity=item.received_quantity,
            confirmed_price=item.confirmed_price,
            received_price=item.received_price,
        )
        for item in items_with_ground_truth
    ]
    mismatched_ids = detect_mismatched_items(ground_truths, extracted_lines)

    return [
        score_order_response_item(
            ground_truth, extracted_lines, known_mismatched_target_ids=mismatched_ids
        )
        for ground_truth in ground_truths
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--documents-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        all_rows: list[dict] = []
        all_scores: list[OrderResponseScore] = []

        for filename, order_id in load_mapping(args.mapping):
            document_path = args.documents_dir / filename
            scores = score_order(
                db,
                order_id,
                file_bytes=document_path.read_bytes(),
                content_type=_content_type_for(document_path),
            )
            all_rows.extend(order_response_csv_rows(document=filename, scores=scores))
            all_scores.extend(scores)

        _write_csv(args.out / "order_response_validation.csv", all_rows)

        if all_scores:
            aggregate = aggregate_order_response_scores(all_scores)
            report = order_response_markdown_report(aggregate)
            (args.out / "order_response_report.md").write_text(report, encoding="utf-8")
            print(report)
        else:
            print("No scored OrderItem — nothing to report.", file=sys.stderr)
    finally:
        db.close()


def _write_csv(path: Path, rows: list[dict]) -> None:
    import csv

    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
