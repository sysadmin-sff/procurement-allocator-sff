"""Tests for the sol/luna dual-run comparison used by price-ingestion (and
unconfirmed order-response) validation — see ADR-0044 §5. Agreement is
computed by comparing each pipeline's own matching decision, not by
re-deriving it here.
"""

import uuid

from app.price_ingestion.extraction import ExtractedPriceLine
from app.price_ingestion.matching import MatchDecision, MatchedLine
from app.scripts.validation.scoring import compare_dual_model_lines


def _matched_line(*, raw_name="Widget", action="match", material_id=None, confidence=0.9):
    return MatchedLine(
        extracted=ExtractedPriceLine(
            raw_name=raw_name,
            raw_sku=None,
            price=10.0,
            currency="USD",
            availability=None,
            min_order_qty=None,
            page_number=1,
        ),
        decision=MatchDecision(
            action=action,
            material_id=material_id,
            confidence=confidence,
            reasoning="irrelevant",
        ),
    )


def test_agrees_when_both_models_match_the_same_material():
    material_id = uuid.uuid4()
    sol_lines = [_matched_line(action="match", material_id=material_id)]
    luna_lines = [_matched_line(action="match", material_id=material_id)]

    comparisons = compare_dual_model_lines(sol_lines, luna_lines)

    assert len(comparisons) == 1
    assert comparisons[0].needs_manual_review is False


def test_disagrees_when_models_match_different_materials():
    sol_lines = [_matched_line(action="match", material_id=uuid.uuid4())]
    luna_lines = [_matched_line(action="match", material_id=uuid.uuid4())]

    comparisons = compare_dual_model_lines(sol_lines, luna_lines)

    assert comparisons[0].needs_manual_review is True


def test_disagrees_when_one_model_matches_and_other_says_not_found():
    material_id = uuid.uuid4()
    sol_lines = [_matched_line(action="match", material_id=material_id)]
    luna_lines = [_matched_line(action="not_found", material_id=None)]

    comparisons = compare_dual_model_lines(sol_lines, luna_lines)

    assert comparisons[0].needs_manual_review is True


def test_agrees_when_both_models_say_not_found():
    sol_lines = [_matched_line(action="not_found", material_id=None)]
    luna_lines = [_matched_line(action="not_found", material_id=None)]

    comparisons = compare_dual_model_lines(sol_lines, luna_lines)

    assert comparisons[0].needs_manual_review is False


def test_compares_multiple_lines_by_position():
    agree_material = uuid.uuid4()
    sol_lines = [
        _matched_line(raw_name="A", action="match", material_id=agree_material),
        _matched_line(raw_name="B", action="match", material_id=uuid.uuid4()),
    ]
    luna_lines = [
        _matched_line(raw_name="A", action="match", material_id=agree_material),
        _matched_line(raw_name="B", action="match", material_id=uuid.uuid4()),
    ]

    comparisons = compare_dual_model_lines(sol_lines, luna_lines)

    assert comparisons[0].needs_manual_review is False
    assert comparisons[1].needs_manual_review is True
