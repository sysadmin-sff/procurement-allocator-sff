"""Tests for pure scoring logic — see ADR-0044 §3-4. No network, no DB:
inputs are plain dataclasses/values the caller already fetched elsewhere.
"""

import uuid
from decimal import Decimal

from app.order_response_parser.client import ExtractedLine
from app.scripts.validation.scoring import (
    OrderItemGroundTruth,
    aggregate_order_response_scores,
    score_order_response_item,
)


def _extracted_line(*, matched_order_item_id, price, quantity):
    return ExtractedLine(
        raw_description="irrelevant",
        matched_order_item_id=matched_order_item_id,
        price=price,
        quantity=quantity,
        confidence="high",
        reasoning="irrelevant",
    )


def test_scores_correct_match_when_extracted_line_points_to_this_item():
    item_id = uuid.uuid4()
    ground_truth = OrderItemGroundTruth(
        order_item_id=item_id,
        received_quantity=2,
        confirmed_price=None,
        received_price=Decimal("10.500"),
    )
    extracted_lines = [_extracted_line(matched_order_item_id=item_id, price=10.5, quantity=2)]

    score = score_order_response_item(ground_truth, extracted_lines)

    assert score.category == "correct_match"


def test_scores_missing_when_no_extracted_line_references_this_item():
    item_id = uuid.uuid4()
    other_id = uuid.uuid4()
    ground_truth = OrderItemGroundTruth(
        order_item_id=item_id,
        received_quantity=2,
        confirmed_price=None,
        received_price=Decimal("10.500"),
    )
    extracted_lines = [_extracted_line(matched_order_item_id=other_id, price=5.0, quantity=1)]

    score = score_order_response_item(ground_truth, extracted_lines)

    assert score.category == "missing"


def test_scores_missing_when_extracted_lines_empty():
    ground_truth = OrderItemGroundTruth(
        order_item_id=uuid.uuid4(),
        received_quantity=2,
        confirmed_price=None,
        received_price=Decimal("10.500"),
    )

    score = score_order_response_item(ground_truth, [])

    assert score.category == "missing"


def test_scores_mismatched_when_item_was_ground_truth_for_a_different_items_line():
    """The ADR-0039 silent-failure case: this item's ground truth exists, but
    the model attributed some OTHER item's response line to this item instead
    of leaving it missing — i.e. this item itself has no line pointing to it,
    AND it was itself the wrong target for a line meant for another item.

    Scoring one item in isolation can't detect "this item stole another's
    line" by itself — that needs the full-order view. This test instead
    covers the simpler, directly observable case: a line that explicitly
    claims a WRONG order_item_id relative to the known correct pairing,
    passed in via wrong_target_item_ids.
    """
    item_id = uuid.uuid4()
    wrong_target_id = uuid.uuid4()
    ground_truth = OrderItemGroundTruth(
        order_item_id=item_id,
        received_quantity=2,
        confirmed_price=None,
        received_price=Decimal("10.500"),
    )
    extracted_lines = [
        _extracted_line(matched_order_item_id=wrong_target_id, price=10.5, quantity=2)
    ]

    score = score_order_response_item(
        ground_truth,
        extracted_lines,
        known_mismatched_target_ids={item_id},
    )

    assert score.category == "mismatched"


def test_price_match_true_when_extracted_price_equals_confirmed_price_exactly():
    item_id = uuid.uuid4()
    ground_truth = OrderItemGroundTruth(
        order_item_id=item_id,
        received_quantity=2,
        confirmed_price=Decimal("10.500"),
        received_price=None,
    )
    extracted_lines = [_extracted_line(matched_order_item_id=item_id, price=10.5, quantity=2)]

    score = score_order_response_item(ground_truth, extracted_lines)

    assert score.price_match is True


def test_price_match_false_on_any_difference_no_rounding_tolerance():
    item_id = uuid.uuid4()
    ground_truth = OrderItemGroundTruth(
        order_item_id=item_id,
        received_quantity=2,
        confirmed_price=Decimal("10.501"),
        received_price=None,
    )
    extracted_lines = [_extracted_line(matched_order_item_id=item_id, price=10.5, quantity=2)]

    score = score_order_response_item(ground_truth, extracted_lines)

    assert score.price_match is False


def test_price_match_prefers_confirmed_price_over_received_price():
    item_id = uuid.uuid4()
    ground_truth = OrderItemGroundTruth(
        order_item_id=item_id,
        received_quantity=2,
        confirmed_price=Decimal("10.500"),
        received_price=Decimal("99.999"),
    )
    extracted_lines = [_extracted_line(matched_order_item_id=item_id, price=10.5, quantity=2)]

    score = score_order_response_item(ground_truth, extracted_lines)

    assert score.price_match is True


def test_quantity_match_true_when_extracted_quantity_equals_received_quantity():
    item_id = uuid.uuid4()
    ground_truth = OrderItemGroundTruth(
        order_item_id=item_id,
        received_quantity=2,
        confirmed_price=None,
        received_price=None,
    )
    extracted_lines = [_extracted_line(matched_order_item_id=item_id, price=1.0, quantity=2)]

    score = score_order_response_item(ground_truth, extracted_lines)

    assert score.quantity_match is True


def test_quantity_match_false_when_quantities_differ():
    item_id = uuid.uuid4()
    ground_truth = OrderItemGroundTruth(
        order_item_id=item_id,
        received_quantity=2,
        confirmed_price=None,
        received_price=None,
    )
    extracted_lines = [_extracted_line(matched_order_item_id=item_id, price=1.0, quantity=4)]

    score = score_order_response_item(ground_truth, extracted_lines)

    assert score.quantity_match is False


def test_price_and_quantity_match_are_none_when_not_correct_match():
    item_id = uuid.uuid4()
    ground_truth = OrderItemGroundTruth(
        order_item_id=item_id,
        received_quantity=2,
        confirmed_price=Decimal("10.500"),
        received_price=None,
    )

    score = score_order_response_item(ground_truth, [])

    assert score.category == "missing"
    assert score.price_match is None
    assert score.quantity_match is None


def test_aggregate_reports_three_separate_rates_not_one_match_rate():
    item_a, item_b, item_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scores = [
        score_order_response_item(
            OrderItemGroundTruth(item_a, 2, Decimal("10.000"), None),
            [_extracted_line(matched_order_item_id=item_a, price=10.0, quantity=2)],
        ),
        score_order_response_item(
            OrderItemGroundTruth(item_b, 1, Decimal("5.000"), None),
            [],
        ),
        score_order_response_item(
            OrderItemGroundTruth(item_c, 1, Decimal("5.000"), None),
            [_extracted_line(matched_order_item_id=uuid.uuid4(), price=5.0, quantity=1)],
            known_mismatched_target_ids={item_c},
        ),
        # item_c is deliberately flagged via known_mismatched_target_ids above
    ]

    aggregate = aggregate_order_response_scores(scores)

    assert aggregate["correct_match_rate"] == 1 / 3
    assert aggregate["missing_rate"] == 1 / 3
    assert aggregate["mismatched_rate"] == 1 / 3


def test_aggregate_price_and_quantity_accuracy_computed_only_over_correct_match():
    item_a, item_b = uuid.uuid4(), uuid.uuid4()
    scores = [
        score_order_response_item(
            OrderItemGroundTruth(item_a, 2, Decimal("10.000"), None),
            [_extracted_line(matched_order_item_id=item_a, price=10.0, quantity=2)],
        ),
        # missing — must not count toward the price/quantity accuracy denominator
        score_order_response_item(
            OrderItemGroundTruth(item_b, 1, Decimal("5.000"), None),
            [],
        ),
    ]

    aggregate = aggregate_order_response_scores(scores)

    assert aggregate["price_accuracy"] == 1.0
    assert aggregate["quantity_accuracy"] == 1.0
    assert aggregate["price_accuracy_denominator"] == 1
