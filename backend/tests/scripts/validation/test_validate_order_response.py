"""Tests for the order-response validation script's DB-touching logic — see
ADR-0044 §2-4. The OpenAI call (parse_order_response_document) is mocked at
its module boundary, same pattern as test_backfill_material_embeddings.py
mocking embed_text; everything else (loading the Order, filtering to items
with ground truth, scoring) runs against the real test DB.
"""

import json
import uuid
from decimal import Decimal
from unittest.mock import patch

from app.order_response_parser.client import ExtractedLine
from app.scripts.validation.validate_order_response import load_mapping, score_order


def test_load_mapping_parses_filename_and_order_id_pairs(tmp_path):
    order_id = uuid.uuid4()
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(
        json.dumps([{"filename": "resp1.pdf", "order_id": str(order_id)}]),
        encoding="utf-8",
    )

    entries = load_mapping(mapping_path)

    assert entries == [("resp1.pdf", order_id)]


def test_score_order_skips_items_without_ground_truth(
    db_session, make_supplier, make_material, make_order
):
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material()
    order = make_order(supplier, [(material, 2, Decimal("10.000"))])
    # No received_quantity/confirmed_price set on the item -- no ground truth.

    with patch(
        "app.scripts.validation.validate_order_response.parse_order_response_document",
        return_value=[],
    ) as mock_parse:
        scores = score_order(
            session, order.id, file_bytes=b"irrelevant", content_type="application/pdf"
        )

    assert scores == []
    mock_parse.assert_not_called()


def test_score_order_scores_only_items_with_ground_truth(
    db_session, make_supplier, make_material, make_order
):
    session, *_ = db_session
    supplier = make_supplier()
    confirmed_material = make_material(canonical_name="Confirmed Widget")
    unconfirmed_material = make_material(canonical_name="Unconfirmed Widget")
    order = make_order(
        supplier,
        [
            (confirmed_material, 2, Decimal("10.000")),
            (unconfirmed_material, 1, Decimal("5.000")),
        ],
    )
    confirmed_item = next(i for i in order.items if i.material_id == confirmed_material.id)
    confirmed_item.received_quantity = 2
    confirmed_item.confirmed_price = Decimal("10.000")
    session.commit()

    extracted_line = ExtractedLine(
        raw_description="Confirmed Widget x2",
        matched_order_item_id=confirmed_item.id,
        price=10.0,
        quantity=2,
        confidence="high",
        reasoning="irrelevant",
    )

    with patch(
        "app.scripts.validation.validate_order_response.parse_order_response_document",
        return_value=[extracted_line],
    ):
        scores = score_order(
            session, order.id, file_bytes=b"irrelevant", content_type="application/pdf"
        )

    assert len(scores) == 1
    assert scores[0].order_item_id == confirmed_item.id
    assert scores[0].category == "correct_match"


def test_score_order_returns_empty_for_unknown_order(db_session):
    session, *_ = db_session

    scores = score_order(
        session, uuid.uuid4(), file_bytes=b"irrelevant", content_type="application/pdf"
    )

    assert scores == []


def test_score_order_detects_mismatch_end_to_end(
    db_session, make_supplier, make_material, make_order
):
    """Real wiring test for ADR-0044 §3's missing-vs-mismatched algorithm:
    the victim OrderItem's ground truth (qty=2, price=10.000) ends up on a
    line the model attributed to a different, unrelated OrderItem (the
    "thief") -- score_order must classify the victim as mismatched, not
    missing, using detect_mismatched_items under the hood, not a manually
    supplied set."""
    session, *_ = db_session
    supplier = make_supplier()
    victim_material = make_material(canonical_name="Victim Widget")
    thief_material = make_material(canonical_name="Thief Widget")
    order = make_order(
        supplier,
        [
            (victim_material, 2, Decimal("10.000")),
            (thief_material, 9, Decimal("99.000")),
        ],
    )
    victim_item = next(i for i in order.items if i.material_id == victim_material.id)
    thief_item = next(i for i in order.items if i.material_id == thief_material.id)
    victim_item.received_quantity = 2
    victim_item.confirmed_price = Decimal("10.000")
    thief_item.received_quantity = 9
    thief_item.confirmed_price = Decimal("99.000")
    session.commit()

    # The model attributed a line with the VICTIM's numbers to the THIEF.
    stolen_line = ExtractedLine(
        raw_description="Confusing description",
        matched_order_item_id=thief_item.id,
        price=10.0,
        quantity=2,
        confidence="high",
        reasoning="irrelevant",
    )

    with patch(
        "app.scripts.validation.validate_order_response.parse_order_response_document",
        return_value=[stolen_line],
    ):
        scores = score_order(
            session, order.id, file_bytes=b"irrelevant", content_type="application/pdf"
        )

    by_item = {s.order_item_id: s for s in scores}
    assert by_item[victim_item.id].category == "mismatched"
    # thief_item itself IS pointed at by a line (the stolen one) -- per
    # ADR-0044 §3 outcome 1, correct_match is purely about whether some
    # line's matched_order_item_id equals this item's id, so thief_item is
    # correct_match even though that line's numbers belong to victim_item.
    # Its price/quantity accuracy will reflect the mismatch instead (the
    # stolen line's numbers don't match thief's own ground truth).
    assert by_item[thief_item.id].category == "correct_match"
    assert by_item[thief_item.id].price_match is False
    assert by_item[thief_item.id].quantity_match is False
