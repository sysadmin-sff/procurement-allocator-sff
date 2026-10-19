"""Tests for the post-match step in app.order_response_parser.service —
see ADR-0046 §1. A deterministic, code-level link between an "extra" line
(matched_order_item_id is None) and a missing OrderItem, via a stored
SupplierMaterialAlias (origin='order_response') — not an LLM decision.
"""

from app.models import OrderItem
from app.order_response_parser.client import ExtractedLine
from app.order_response_parser.service import parse_order_response


def _line(raw_description, matched_order_item_id=None, confidence="medium", reasoning="r"):
    return ExtractedLine(
        raw_description=raw_description,
        matched_order_item_id=matched_order_item_id,
        price=1.0,
        quantity=1,
        confidence=confidence,
        reasoning=reasoning,
    )


def test_post_match_links_extra_line_to_unique_aliased_missing_item(
    db_session, make_supplier, make_material, make_order, make_alias, monkeypatch
):
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material(canonical_name="3x4 A Elbow")
    order = make_order(supplier, [(material, 4, 2.52)])
    item = order.items[0]
    make_alias(supplier, material, "S-25-00-00070 3X4 A ELBOW BRONZE")

    lines = [_line("S-25-00-00070 3X4 A ELBOW BRONZE", confidence="medium", reasoning="no match")]
    monkeypatch.setattr(
        "app.order_response_parser.service.parse_order_response_document",
        lambda **kwargs: lines,
    )

    matched, missing, extra, alias_matched_ids = parse_order_response(
        session, order.id, file_bytes=b"x", content_type="application/pdf"
    )

    assert len(matched) == 1
    assert matched[0].matched_order_item_id == item.id
    assert matched[0].raw_description == "S-25-00-00070 3X4 A ELBOW BRONZE"
    assert extra == []
    assert missing == []
    assert alias_matched_ids == {item.id}


def test_post_match_preserves_reasoning_prefix_and_confidence(
    db_session, make_supplier, make_material, make_order, make_alias, monkeypatch
):
    """ADR-0046 §1 п.6: confidence is never touched; reasoning is prefixed,
    not replaced."""
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material(canonical_name="3x4 A Elbow")
    order = make_order(supplier, [(material, 4, 2.52)])
    make_alias(supplier, material, "S-25-00-00070 3X4 A ELBOW BRONZE")

    lines = [
        _line(
            "S-25-00-00070 3X4 A ELBOW BRONZE",
            confidence="low",
            reasoning="model saw a B elbow in the order, not A",
        )
    ]
    monkeypatch.setattr(
        "app.order_response_parser.service.parse_order_response_document",
        lambda **kwargs: lines,
    )

    matched, _missing, _extra, _alias_ids = parse_order_response(
        session, order.id, file_bytes=b"x", content_type="application/pdf"
    )

    assert matched[0].confidence == "low"
    assert matched[0].reasoning == (
        "[сопоставлено по сохранённому alias поставщика] model saw a B elbow in the order, not A"
    )


def test_post_match_does_not_guess_when_multiple_order_items_share_material(
    db_session, make_supplier, make_material, make_order, make_alias, monkeypatch
):
    """ADR-0046 §1 п.5: zero or more than one candidate -> no guess."""
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material(canonical_name="3x4 A Elbow")
    order = make_order(supplier, [(material, 4, 2.52), (material, 2, 2.52)])
    make_alias(supplier, material, "S-25-00-00070 3X4 A ELBOW BRONZE")

    lines = [_line("S-25-00-00070 3X4 A ELBOW BRONZE")]
    monkeypatch.setattr(
        "app.order_response_parser.service.parse_order_response_document",
        lambda **kwargs: lines,
    )

    matched, missing, extra, alias_ids = parse_order_response(
        session, order.id, file_bytes=b"x", content_type="application/pdf"
    )

    assert matched == []
    assert len(extra) == 1
    assert extra[0].raw_description == "S-25-00-00070 3X4 A ELBOW BRONZE"
    assert len(missing) == 2
    assert alias_ids == set()


def test_post_match_does_not_guess_when_no_order_item_has_the_material(
    db_session, make_supplier, make_material, make_order, make_alias, monkeypatch
):
    session, *_ = db_session
    supplier = make_supplier()
    ordered_material = make_material(canonical_name="Something else entirely")
    aliased_material = make_material(canonical_name="3x4 A Elbow")
    order = make_order(supplier, [(ordered_material, 1, 9.99)])
    make_alias(supplier, aliased_material, "S-25-00-00070 3X4 A ELBOW BRONZE")

    lines = [_line("S-25-00-00070 3X4 A ELBOW BRONZE")]
    monkeypatch.setattr(
        "app.order_response_parser.service.parse_order_response_document",
        lambda **kwargs: lines,
    )

    matched, missing, extra, alias_ids = parse_order_response(
        session, order.id, file_bytes=b"x", content_type="application/pdf"
    )

    assert matched == []
    assert len(extra) == 1
    assert len(missing) == 1
    assert alias_ids == set()


def test_post_match_never_overwrites_a_model_match(
    db_session, make_supplier, make_material, make_order, make_alias, monkeypatch
):
    """A line the model already matched (matched_order_item_id is not
    None) is never touched by post-match, even if a suitable alias
    exists."""
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material(canonical_name="3x4 A Elbow")
    order = make_order(supplier, [(material, 4, 2.52)])
    item = order.items[0]
    make_alias(supplier, material, "S-25-00-00070 3X4 A ELBOW BRONZE")

    lines = [
        _line(
            "S-25-00-00070 3X4 A ELBOW BRONZE",
            matched_order_item_id=item.id,
            confidence="high",
            reasoning="model matched this directly",
        )
    ]
    monkeypatch.setattr(
        "app.order_response_parser.service.parse_order_response_document",
        lambda **kwargs: lines,
    )

    matched, _missing, _extra, alias_ids = parse_order_response(
        session, order.id, file_bytes=b"x", content_type="application/pdf"
    )

    assert len(matched) == 1
    assert matched[0].reasoning == "model matched this directly"
    assert matched[0].confidence == "high"
    assert alias_ids == set()


def test_post_match_excludes_order_item_already_matched_by_model_on_another_line(
    db_session, make_supplier, make_material, make_order, make_alias, monkeypatch
):
    """ADR-0046 §1 п.4: an OrderItem the model matched to a DIFFERENT line
    is not a candidate for this line's post-match, even though this line
    never got that match itself."""
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material(canonical_name="3x4 A Elbow")
    order = make_order(supplier, [(material, 4, 2.52), (material, 4, 2.52)])
    item_1, item_2 = order.items
    make_alias(supplier, material, "S-25-00-00070 3X4 A ELBOW BRONZE")

    lines = [
        _line("Some other line the model matched", matched_order_item_id=item_1.id),
        _line("S-25-00-00070 3X4 A ELBOW BRONZE"),
    ]
    monkeypatch.setattr(
        "app.order_response_parser.service.parse_order_response_document",
        lambda **kwargs: lines,
    )

    matched, missing, extra, alias_ids = parse_order_response(
        session, order.id, file_bytes=b"x", content_type="application/pdf"
    )

    # item_1 taken by the model's own match; item_2 is the only remaining
    # candidate and gets the post-match.
    matched_ids = {m.matched_order_item_id for m in matched}
    assert matched_ids == {item_1.id, item_2.id}
    assert extra == []
    assert missing == []
    assert alias_ids == {item_2.id}


def test_post_match_does_not_assign_the_same_order_item_to_two_extra_lines(
    db_session, make_supplier, make_material, make_order, make_alias, monkeypatch
):
    """ADR-0046 §1 п.4: two different extra-texts both matching the same
    alias must not both claim the one eligible OrderItem."""
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material(canonical_name="3x4 A Elbow")
    order = make_order(supplier, [(material, 4, 2.52)])
    item = order.items[0]
    make_alias(supplier, material, "S-25-00-00070 3X4 A ELBOW BRONZE")

    lines = [
        _line("S-25-00-00070 3X4 A ELBOW BRONZE"),
        _line("s-25-00-00070  3x4 a elbow bronze"),  # normalizes to the same text
    ]
    monkeypatch.setattr(
        "app.order_response_parser.service.parse_order_response_document",
        lambda **kwargs: lines,
    )

    matched, missing, extra, alias_ids = parse_order_response(
        session, order.id, file_bytes=b"x", content_type="application/pdf"
    )

    assert len(matched) == 1
    assert matched[0].matched_order_item_id == item.id
    assert len(extra) == 1
    assert missing == []
    assert alias_ids == {item.id}


def test_post_match_ignores_alias_of_another_supplier(
    db_session, make_supplier, make_material, make_order, make_alias, monkeypatch
):
    session, *_ = db_session
    supplier_a = make_supplier(name="Supplier A")
    supplier_b = make_supplier(name="Supplier B")
    material = make_material(canonical_name="3x4 A Elbow")
    order = make_order(supplier_b, [(material, 4, 2.52)])
    make_alias(supplier_a, material, "S-25-00-00070 3X4 A ELBOW BRONZE")

    lines = [_line("S-25-00-00070 3X4 A ELBOW BRONZE")]
    monkeypatch.setattr(
        "app.order_response_parser.service.parse_order_response_document",
        lambda **kwargs: lines,
    )

    matched, missing, extra, alias_ids = parse_order_response(
        session, order.id, file_bytes=b"x", content_type="application/pdf"
    )

    assert matched == []
    assert len(extra) == 1
    assert len(missing) == 1
    assert alias_ids == set()


def test_post_match_ignores_alias_with_price_import_origin(
    db_session, make_supplier, make_material, make_order, make_alias, monkeypatch
):
    """ADR-0046 §1/§4: post-match only reads origin='order_response'
    aliases — a price-ingestion-confirmed alias is a different kind of
    confirmation (price-list vocabulary, not an order-response document)
    and must not silently link an order-response line."""
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material(canonical_name="3x4 A Elbow")
    order = make_order(supplier, [(material, 4, 2.52)])
    make_alias(supplier, material, "S-25-00-00070 3X4 A ELBOW BRONZE", origin="price_import")

    lines = [_line("S-25-00-00070 3X4 A ELBOW BRONZE")]
    monkeypatch.setattr(
        "app.order_response_parser.service.parse_order_response_document",
        lambda **kwargs: lines,
    )

    matched, missing, extra, alias_ids = parse_order_response(
        session, order.id, file_bytes=b"x", content_type="application/pdf"
    )

    assert matched == []
    assert len(extra) == 1
    assert len(missing) == 1
    assert alias_ids == set()


def test_post_match_excludes_declined_order_item(
    db_session, make_supplier, make_material, make_order, make_alias, monkeypatch
):
    from datetime import datetime, timezone

    session, *_ = db_session
    supplier = make_supplier()
    material = make_material(canonical_name="3x4 A Elbow")
    order = make_order(supplier, [(material, 4, 2.52)])
    item = order.items[0]
    item.declined_at = datetime.now(timezone.utc)
    session.flush()
    make_alias(supplier, material, "S-25-00-00070 3X4 A ELBOW BRONZE")

    lines = [_line("S-25-00-00070 3X4 A ELBOW BRONZE")]
    monkeypatch.setattr(
        "app.order_response_parser.service.parse_order_response_document",
        lambda **kwargs: lines,
    )

    matched, missing, extra, alias_ids = parse_order_response(
        session, order.id, file_bytes=b"x", content_type="application/pdf"
    )

    assert matched == []
    assert len(extra) == 1
    assert missing == []  # declined items are excluded from missing too (ADR-0043)
    assert alias_ids == set()
    assert isinstance(item, OrderItem)  # sanity: fixture gave us the right item


def test_post_match_normalizes_case_and_collapsed_whitespace(
    db_session, make_supplier, make_material, make_order, make_alias, monkeypatch
):
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material(canonical_name="3x4 A Elbow")
    order = make_order(supplier, [(material, 4, 2.52)])
    item = order.items[0]
    make_alias(supplier, material, "S-25-00-00070 3X4 A ELBOW BRONZE")

    lines = [_line("s-25-00-00070  3x4 a elbow bronze")]
    monkeypatch.setattr(
        "app.order_response_parser.service.parse_order_response_document",
        lambda **kwargs: lines,
    )

    matched, _missing, extra, alias_ids = parse_order_response(
        session, order.id, file_bytes=b"x", content_type="application/pdf"
    )

    assert len(matched) == 1
    assert matched[0].matched_order_item_id == item.id
    assert extra == []
    assert alias_ids == {item.id}
