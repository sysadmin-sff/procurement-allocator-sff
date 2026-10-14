"""Tests for CSV row building and markdown report rendering — see
ADR-0044 §6. Pure formatting over already-computed scores/comparisons.
"""

import csv
import io
import uuid

from app.scripts.validation.csv_report import (
    order_response_csv_rows,
    order_response_markdown_report,
    price_ingestion_csv_rows,
    price_ingestion_markdown_report,
)
from app.scripts.validation.scoring import (
    DualModelComparison,
    OrderResponseScore,
    aggregate_order_response_scores,
)


def test_order_response_csv_rows_include_document_and_category():
    item_id = uuid.uuid4()
    score = OrderResponseScore(
        order_item_id=item_id, category="correct_match", price_match=True, quantity_match=False
    )

    rows = order_response_csv_rows(document="resp1.pdf", scores=[score])

    assert rows == [
        {
            "document": "resp1.pdf",
            "order_item_id": str(item_id),
            "category": "correct_match",
            "price_match": "True",
            "quantity_match": "False",
            "manual_label": "",
        }
    ]


def test_order_response_csv_rows_write_as_valid_csv():
    item_id = uuid.uuid4()
    score = OrderResponseScore(
        order_item_id=item_id, category="missing", price_match=None, quantity_match=None
    )
    rows = order_response_csv_rows(document="resp1.pdf", scores=[score])

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

    parsed = list(csv.DictReader(io.StringIO(buffer.getvalue())))
    assert parsed[0]["category"] == "missing"
    assert parsed[0]["price_match"] == ""


def test_order_response_markdown_report_shows_three_separate_rates():
    scores = [
        OrderResponseScore(uuid.uuid4(), "correct_match", True, True),
        OrderResponseScore(uuid.uuid4(), "missing", None, None),
        OrderResponseScore(uuid.uuid4(), "mismatched", None, None),
    ]
    aggregate = aggregate_order_response_scores(scores)

    report = order_response_markdown_report(aggregate)

    assert "correct_match" in report
    assert "missing" in report
    assert "mismatched" in report
    # the three rates must appear as distinct numbers, not folded into one
    assert str(round(aggregate["correct_match_rate"] * 100, 1)) in report
    assert str(round(aggregate["missing_rate"] * 100, 1)) in report
    assert str(round(aggregate["mismatched_rate"] * 100, 1)) in report


def test_price_ingestion_csv_rows_include_manual_review_flag():
    comparison = DualModelComparison(
        raw_name="Widget",
        needs_manual_review=True,
        sol_line=_fake_matched_line("match"),
        luna_line=_fake_matched_line("not_found"),
    )

    rows = price_ingestion_csv_rows(document="price1.pdf", comparisons=[comparison])

    assert rows[0]["raw_name"] == "Widget"
    assert rows[0]["needs_manual_review"] == "True"
    assert rows[0]["sol_action"] == "match"
    assert rows[0]["luna_action"] == "not_found"
    assert rows[0]["manual_label"] == ""


def test_price_ingestion_markdown_report_shows_manual_review_rate_separately_from_accuracy():
    comparisons = [
        DualModelComparison(
            "A", False, _fake_matched_line("match"), _fake_matched_line("match")
        ),
        DualModelComparison(
            "B", True, _fake_matched_line("match"), _fake_matched_line("not_found")
        ),
    ]

    report = price_ingestion_markdown_report(comparisons, manually_labeled_correct_count=1)

    assert "50" in report  # 1/2 needs manual review
    assert "не является доказательством правильности" in report


def _fake_matched_line(action: str):
    from app.price_ingestion.extraction import ExtractedPriceLine
    from app.price_ingestion.matching import MatchDecision, MatchedLine

    return MatchedLine(
        extracted=ExtractedPriceLine(
            raw_name="Widget",
            raw_sku=None,
            price=10.0,
            currency="USD",
            availability=None,
            min_order_qty=None,
            page_number=1,
        ),
        decision=MatchDecision(
            action=action,
            material_id=uuid.uuid4() if action == "match" else None,
            confidence=0.9,
            reasoning="irrelevant",
        ),
    )
