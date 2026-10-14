"""Tests for detect_mismatched_items — the order-level algorithm that
distinguishes missing from mismatched, see ADR-0044 §3. mismatched requires
positive NUMERIC evidence (price/quantity of the extracted line matches
this item's ground truth and not the other item's it was attributed to);
missing is the safe default whenever that evidence is absent or ambiguous.
"""

import uuid
from decimal import Decimal

from app.order_response_parser.client import ExtractedLine
from app.scripts.validation.scoring import OrderItemGroundTruth, detect_mismatched_items


def _extracted_line(*, matched_order_item_id, price, quantity):
    return ExtractedLine(
        raw_description="irrelevant",
        matched_order_item_id=matched_order_item_id,
        price=price,
        quantity=quantity,
        confidence="high",
        reasoning="irrelevant",
    )


def test_detects_mismatch_when_stolen_lines_numbers_match_the_victim_not_the_thief():
    victim, thief = uuid.uuid4(), uuid.uuid4()
    ground_truths = [
        OrderItemGroundTruth(victim, 2, Decimal("10.000"), None),
        OrderItemGroundTruth(thief, 9, Decimal("99.000"), None),
    ]
    # Line attributed to `thief`, but its numbers match `victim`'s ground
    # truth, not thief's own -- positive evidence victim's line was stolen.
    extracted_lines = [_extracted_line(matched_order_item_id=thief, price=10.0, quantity=2)]

    mismatched = detect_mismatched_items(ground_truths, extracted_lines)

    assert mismatched == {victim}


def test_no_mismatch_when_victim_candidate_already_has_its_own_correct_match():
    victim, thief = uuid.uuid4(), uuid.uuid4()
    ground_truths = [
        OrderItemGroundTruth(victim, 2, Decimal("10.000"), None),
        OrderItemGroundTruth(thief, 9, Decimal("99.000"), None),
    ]
    extracted_lines = [
        _extracted_line(matched_order_item_id=victim, price=10.0, quantity=2),
        _extracted_line(matched_order_item_id=thief, price=99.0, quantity=9),
    ]

    mismatched = detect_mismatched_items(ground_truths, extracted_lines)

    assert mismatched == set()


def test_no_evidence_defaults_to_missing_not_mismatched():
    victim, thief = uuid.uuid4(), uuid.uuid4()
    ground_truths = [
        OrderItemGroundTruth(victim, 2, Decimal("10.000"), None),
        OrderItemGroundTruth(thief, 9, Decimal("99.000"), None),
    ]
    # thief's line has numbers matching NEITHER victim nor thief's own
    # ground truth -- no positive evidence of theft, stay missing.
    extracted_lines = [_extracted_line(matched_order_item_id=thief, price=50.0, quantity=5)]

    mismatched = detect_mismatched_items(ground_truths, extracted_lines)

    assert mismatched == set()


def test_ambiguous_evidence_when_victim_and_thief_ground_truth_coincide_defaults_to_missing():
    victim, thief = uuid.uuid4(), uuid.uuid4()
    # Both items happen to share the same ground truth price/quantity --
    # the stolen line can't be used as evidence for one over the other.
    ground_truths = [
        OrderItemGroundTruth(victim, 2, Decimal("10.000"), None),
        OrderItemGroundTruth(thief, 2, Decimal("10.000"), None),
    ]
    extracted_lines = [_extracted_line(matched_order_item_id=thief, price=10.0, quantity=2)]

    mismatched = detect_mismatched_items(ground_truths, extracted_lines)

    assert mismatched == set()


def test_evidence_must_also_fail_to_match_the_thiefs_own_ground_truth():
    """A line attributed to `thief` whose numbers happen to equal victim's
    ground truth AND thief's own ground truth is ambiguous (matches both),
    not positive evidence of theft -- stays missing. Distinct from the
    coincidence test above: here only ONE of victim's two ground-truth
    values coincides with thief's, so the evidence is partial, not total."""
    victim, thief = uuid.uuid4(), uuid.uuid4()
    ground_truths = [
        OrderItemGroundTruth(victim, 2, Decimal("10.000"), None),
        OrderItemGroundTruth(thief, 2, Decimal("99.000"), None),
    ]
    # Line's quantity (2) matches both victim and thief; price (99) matches
    # only thief -- overall this is thief's own correct match, not theft.
    extracted_lines = [_extracted_line(matched_order_item_id=thief, price=99.0, quantity=2)]

    mismatched = detect_mismatched_items(ground_truths, extracted_lines)

    assert mismatched == set()


def test_detects_multiple_independent_mismatches():
    victim_a, thief_a, victim_b, thief_b = (uuid.uuid4() for _ in range(4))
    ground_truths = [
        OrderItemGroundTruth(victim_a, 2, Decimal("10.000"), None),
        OrderItemGroundTruth(thief_a, 9, Decimal("99.000"), None),
        OrderItemGroundTruth(victim_b, 3, Decimal("20.000"), None),
        OrderItemGroundTruth(thief_b, 7, Decimal("77.000"), None),
    ]
    extracted_lines = [
        _extracted_line(matched_order_item_id=thief_a, price=10.0, quantity=2),
        _extracted_line(matched_order_item_id=thief_b, price=20.0, quantity=3),
    ]

    mismatched = detect_mismatched_items(ground_truths, extracted_lines)

    assert mismatched == {victim_a, victim_b}
