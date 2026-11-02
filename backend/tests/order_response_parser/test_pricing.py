"""Per-foot -> per-piece price normalization for order responses — ADR-0050.

The parametrized rows are Eastern Metal Supply Quote V3EAX8 (2026-10-28),
the document that motivated the ADR: Required (linear feet) | Qty (PCS) |
description | unit price per foot | amount. Pure functions, no DB/OpenAI.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.order_response_parser.client import (
    RawExtractedLine,
    RawExtractionResult,
    parse_order_response_document,
)
from app.order_response_parser.pricing import normalize_line


def _raw(**overrides) -> RawExtractedLine:
    fields = {
        "raw_description": "2 X 6 SMB BRZ 28' 6005",
        "matched_order_item_id": None,
        "quantity": 8,
        "printed_unit_price": 2.8,
        "price_basis": "linear_foot",
        "priced_quantity": 224.0,
        "line_total": 627.2,
        "confidence": "high",
        "reasoning": "",
    }
    fields.update(overrides)
    return RawExtractedLine(**fields)


QUOTE_V3EAX8 = [
    # (description, required_ft, pcs, price_per_ft, amount, expected_per_piece)
    ("2 X 6 SMB BRZ 28'", 224.0, 8, 2.8, 627.2, 78.4),
    ("2 X 6 SMB BRZ 24'", 24.0, 1, 2.8, 67.2, 67.2),
    ("2 X 6 SMB BRZ 22'", 264.0, 12, 2.8, 739.2, 61.6),
    ("2 X 2 PATIO BRZ 30'", 360.0, 12, 2.07, 745.2, 62.1),
    ("2 X 2 PATIO BRZ 24'", 72.0, 3, 2.07, 149.04, 49.68),
    ("1 X 2 OPEN BACK BRZ 30'", 240.0, 8, 1.11, 266.4, 33.3),
    ("1 X 2 OPEN BACK BRZ 24'", 96.0, 4, 1.11, 106.56, 26.64),
    ("1 X 3 X 25' SMS", 50.0, 2, 1.78, 89.0, 44.5),
]


@pytest.mark.parametrize("description,required_ft,pcs,per_ft,amount,expected", QUOTE_V3EAX8)
def test_linear_foot_line_becomes_per_piece_price(
    description, required_ft, pcs, per_ft, amount, expected
):
    line = normalize_line(
        _raw(
            raw_description=description,
            quantity=pcs,
            printed_unit_price=per_ft,
            price_basis="linear_foot",
            priced_quantity=required_ft,
            line_total=amount,
        )
    )

    assert line.price == expected
    assert line.quantity == pcs
    assert line.price_warning is None
    assert line.price_note is not None
    assert f"{pcs} шт" in line.price_note


def test_price_note_spells_out_the_conversion():
    line = normalize_line(_raw())

    assert line.price_note == "$2.800/фут × 224 фт = $627.20 ÷ 8 шт = $78.400/шт"


def test_per_piece_line_in_the_same_document_is_left_as_is():
    """HR-5 PICKET: Required == Qty (10/10) — already priced per piece."""
    line = normalize_line(
        _raw(
            raw_description='HR-5 1X.035 PICKET 19\'10" BRONZE 6063',
            quantity=10,
            printed_unit_price=19.67,
            price_basis="piece",
            priced_quantity=10.0,
            line_total=196.7,
        )
    )

    assert line.price == 19.67
    assert line.price_note is None
    assert line.price_warning is None


def test_linear_foot_without_line_total_uses_feet_times_price_over_pieces():
    line = normalize_line(_raw(line_total=None))

    assert line.price == 78.4
    assert line.price_warning is None


def test_total_that_does_not_match_feet_times_price_is_flagged():
    # 224 ft x $2.80 = 627.20, but the document says 600.00.
    line = normalize_line(_raw(line_total=600.0))

    assert line.price == 75.0  # still Amount / Qty — what the supplier bills
    assert line.price_warning is not None


def test_piece_price_that_does_not_match_total_is_flagged():
    line = normalize_line(
        _raw(
            price_basis="piece",
            printed_unit_price=19.67,
            quantity=10,
            priced_quantity=None,
            line_total=200.0,
        )
    )

    assert line.price == 19.67
    assert line.price_warning is not None


def test_linear_foot_without_pieces_keeps_printed_price_and_warns():
    line = normalize_line(_raw(quantity=None))

    assert line.price == 2.8
    assert line.price_warning is not None


def test_linear_foot_without_total_or_feet_keeps_printed_price_and_warns():
    line = normalize_line(_raw(line_total=None, priced_quantity=None))

    assert line.price == 2.8
    assert line.price_warning is not None


def test_piece_line_without_total_has_no_note_and_no_warning():
    line = normalize_line(
        _raw(
            price_basis="piece",
            printed_unit_price=5.5,
            quantity=2,
            priced_quantity=None,
            line_total=None,
        )
    )

    assert line.price == 5.5
    assert line.price_note is None
    assert line.price_warning is None


def test_matching_fields_pass_through_unchanged():
    item_id = uuid.uuid4()
    line = normalize_line(_raw(matched_order_item_id=item_id, confidence="medium", reasoning="r"))

    assert line.matched_order_item_id == item_id
    assert line.confidence == "medium"
    assert line.reasoning == "r"
    assert line.raw_description == "2 X 6 SMB BRZ 28' 6005"


def test_parse_order_response_document_returns_normalized_lines():
    fake_response = SimpleNamespace(output_parsed=RawExtractionResult(lines=[_raw()]))
    fake_client = SimpleNamespace(responses=SimpleNamespace(parse=lambda **kwargs: fake_response))

    with (
        patch("app.order_response_parser.client.OpenAI", return_value=fake_client),
        patch("app.order_response_parser.client.settings") as fake_settings,
    ):
        fake_settings.openai_order_response_model = "test-model"
        lines = parse_order_response_document(
            file_bytes=b"%PDF", content_type="application/pdf", order_items=[]
        )

    assert [line.price for line in lines] == [78.4]
    assert lines[0].quantity == 8
