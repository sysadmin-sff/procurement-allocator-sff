"""Price-ingestion (and unconfirmed order-response) dual-model accuracy
validation — see ADR-0044 §5-6.

No independent ground truth exists for these documents (price lists;
unconfirmed supplier responses) — a PriceListEntry decision is itself a
human decision made FROM the model's output, not an independent fact that
existed before it (see ADR-0044 "Контекст"). Instead, each document is run
through both configured models (sol, luna) and their results compared
line by line: agreement needs no manual review; disagreement is the
sample that does. Agreement is NOT proof of correctness (see
run_dual_model's docstring and ADR-0044 §5) — do not report it as such.

READ-ONLY: only reads the prod DB (the Material catalog, via
match_price_list_lines). session.commit() is never called in this file —
see ADR-0044 §2 for the same invariant on the order-response script.

Usage:
    docker compose exec backend python -m app.scripts.validation.validate_price_ingestion \\
        --documents-dir ./docs --supplier-id <uuid> --out ./report
"""

from __future__ import annotations

import argparse
import csv
import sys
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.price_ingestion.extraction import extract_price_list_lines, validate_content_type
from app.price_ingestion.matching import MatchedLine, match_price_list_lines
from app.scripts.validation.csv_report import (
    price_ingestion_csv_rows,
    price_ingestion_markdown_report,
)
from app.scripts.validation.scoring import DualModelComparison, compare_dual_model_lines

_SOL_MODEL = "gpt-5.6-sol"
_LUNA_MODEL = "gpt-5.6-luna"

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


@contextmanager
def _price_ingestion_model(model: str):
    """Temporarily overrides settings.openai_price_ingestion_model for the
    duration of one pipeline run, then restores it — see ADR-0044 §5: both
    models run within a single script invocation, not two separate runs
    the user would have to diff by hand."""
    original = settings.openai_price_ingestion_model
    settings.openai_price_ingestion_model = model
    try:
        yield
    finally:
        settings.openai_price_ingestion_model = original


def run_pipeline(
    db: Session, supplier_id, file_bytes: bytes, content_type: str
) -> list[MatchedLine]:
    """One full extract+match pass under whichever model is currently set
    in settings.openai_price_ingestion_model."""
    lines = extract_price_list_lines(file_bytes=file_bytes, content_type=content_type)
    return match_price_list_lines(db, supplier_id, lines)


def run_dual_model(
    db: Session, supplier_id, file_bytes: bytes, content_type: str
) -> list[DualModelComparison]:
    """Runs the document through sol then luna (see _price_ingestion_model)
    and compares line by line — see ADR-0044 §5. Agreement between the two
    is NOT evidence of correctness; it only tells you whether the line
    needs manual review."""
    with _price_ingestion_model(_SOL_MODEL):
        sol_lines = run_pipeline(db, supplier_id, file_bytes, content_type)
    with _price_ingestion_model(_LUNA_MODEL):
        luna_lines = run_pipeline(db, supplier_id, file_bytes, content_type)

    return compare_dual_model_lines(sol_lines, luna_lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents-dir", type=Path, required=True)
    parser.add_argument("--supplier-id", type=str, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--manually-labeled-correct-count",
        type=int,
        default=0,
        help=(
            "After filling in manual_label on the needs_manual_review CSV rows, "
            "pass the count of rows manually confirmed correct to include "
            "accuracy in the markdown report — see ADR-0044 §5."
        ),
    )
    args = parser.parse_args()

    import uuid as uuid_module

    supplier_id = uuid_module.UUID(args.supplier_id)
    args.out.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        all_rows: list[dict] = []
        all_comparisons: list[DualModelComparison] = []

        for document_path in sorted(args.documents_dir.iterdir()):
            if document_path.is_dir():
                continue
            content_type = _content_type_for(document_path)
            validate_content_type(content_type)

            comparisons = run_dual_model(
                db, supplier_id, document_path.read_bytes(), content_type
            )
            all_rows.extend(
                price_ingestion_csv_rows(document=document_path.name, comparisons=comparisons)
            )
            all_comparisons.extend(comparisons)

        _write_csv(args.out / "price_ingestion_validation.csv", all_rows)

        if all_comparisons:
            report = price_ingestion_markdown_report(
                all_comparisons,
                manually_labeled_correct_count=args.manually_labeled_correct_count,
            )
            (args.out / "price_ingestion_report.md").write_text(report, encoding="utf-8")
            print(report)
        else:
            print("No documents processed — nothing to report.", file=sys.stderr)
    finally:
        db.close()


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
