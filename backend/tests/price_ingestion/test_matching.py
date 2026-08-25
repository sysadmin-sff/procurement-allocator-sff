"""Tests for app.price_ingestion.matching — see ADR-0019 §2-4.

Alias short-circuit must skip embedding + LLM calls entirely (asserted via
mock.assert_not_called on both). Normal path mocks both embed_text and the
LLM decision call. Duplicate-detection reuses embeddings already computed
during matching, so no extra embed_text call is needed for that step.
"""

import uuid
from unittest.mock import patch

from app.models import SupplierMaterialAlias
from app.price_ingestion.extraction import ExtractedPriceLine
from app.price_ingestion.matching import MatchDecision, match_price_list_lines


def _line(raw_name="Some Material", price=10.0, raw_sku=None):
    return ExtractedPriceLine(
        raw_name=raw_name,
        raw_sku=raw_sku,
        price=price,
        currency="USD",
        availability=None,
        min_order_qty=None,
    )


def test_known_alias_skips_embedding_and_llm_entirely(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    material = make_material()
    session.add(
        SupplierMaterialAlias(
            supplier_id=supplier.id,
            material_id=material.id,
            supplier_raw_name="Known Raw Name",
        )
    )
    session.commit()

    line = _line(raw_name="Known Raw Name")

    with patch("app.price_ingestion.matching.embed_text") as mock_embed, patch(
        "app.price_ingestion.matching._decide_match"
    ) as mock_llm:
        results = match_price_list_lines(session, supplier.id, [line])

    mock_embed.assert_not_called()
    mock_llm.assert_not_called()
    assert len(results) == 1
    assert results[0].decision.action == "match"
    assert results[0].decision.material_id == material.id
    assert results[0].decision.confidence == 1.0
    assert results[0].decision.reasoning == "known alias"


def test_unknown_line_goes_through_vector_search_and_llm(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    candidate = make_material(canonical_name="Candidate Material")
    candidate.embedding = [0.5] * 1536
    session.commit()

    line = _line(raw_name="New Raw Name")
    fake_decision = MatchDecision(
        action="match",
        material_id=candidate.id,
        confidence=0.9,
        reasoning="matches by attributes",
        suggested_internal_sku=None,
    )

    with patch(
        "app.price_ingestion.matching.embed_text", return_value=[0.5] * 1536
    ) as mock_embed, patch(
        "app.price_ingestion.matching._decide_match", return_value=fake_decision
    ) as mock_llm:
        results = match_price_list_lines(session, supplier.id, [line])

    mock_embed.assert_called_once()
    mock_llm.assert_called_once()
    assert results[0].decision.action == "match"
    assert results[0].decision.material_id == candidate.id


def test_two_new_lines_with_close_embeddings_flag_each_other_as_duplicates(
    db_session, make_supplier
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    line_a = _line(raw_name="Screen Type A")
    line_b = _line(raw_name="Screen Type A Variant")

    decision_new = MatchDecision(
        action="new",
        material_id=None,
        confidence=0.8,
        reasoning="no close match found",
        suggested_internal_sku="NEW-SKU-1",
    )

    close_embedding_a = [1.0] + [0.0] * 1535
    close_embedding_b = [0.99] + [0.01] * 1535

    with patch(
        "app.price_ingestion.matching.embed_text",
        side_effect=[close_embedding_a, close_embedding_b],
    ), patch(
        "app.price_ingestion.matching._decide_match", return_value=decision_new
    ):
        results = match_price_list_lines(session, supplier.id, [line_a, line_b])

    assert results[0].possible_duplicate_of == [1]
    assert results[1].possible_duplicate_of == [0]


def test_new_lines_with_far_embeddings_do_not_flag_each_other(
    db_session, make_supplier
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    line_a = _line(raw_name="Screen Type A")
    line_b = _line(raw_name="Completely Different Item")

    decision_new = MatchDecision(
        action="new",
        material_id=None,
        confidence=0.8,
        reasoning="no close match found",
        suggested_internal_sku="NEW-SKU-1",
    )

    far_embedding_a = [1.0] + [0.0] * 1535
    far_embedding_b = [0.0, 1.0] + [0.0] * 1534

    with patch(
        "app.price_ingestion.matching.embed_text",
        side_effect=[far_embedding_a, far_embedding_b],
    ), patch(
        "app.price_ingestion.matching._decide_match", return_value=decision_new
    ):
        results = match_price_list_lines(session, supplier.id, [line_a, line_b])

    assert results[0].possible_duplicate_of == []
    assert results[1].possible_duplicate_of == []


def test_matched_lines_are_not_considered_for_duplicate_detection(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    candidate = make_material()
    candidate.embedding = [1.0] + [0.0] * 1535
    session.commit()

    line_a = _line(raw_name="Matched Line")
    line_b = _line(raw_name="New Line")

    decision_match = MatchDecision(
        action="match",
        material_id=candidate.id,
        confidence=0.9,
        reasoning="matches",
        suggested_internal_sku=None,
    )
    decision_new = MatchDecision(
        action="new",
        material_id=None,
        confidence=0.8,
        reasoning="no match",
        suggested_internal_sku="NEW-SKU-2",
    )

    with patch(
        "app.price_ingestion.matching.embed_text",
        side_effect=[[1.0] + [0.0] * 1535, [1.0] + [0.0] * 1535],
    ), patch(
        "app.price_ingestion.matching._decide_match",
        side_effect=[decision_match, decision_new],
    ):
        results = match_price_list_lines(session, supplier.id, [line_a, line_b])

    assert results[0].possible_duplicate_of == []
    assert results[1].possible_duplicate_of == []


def test_hallucinated_material_id_is_downgraded_to_new(
    db_session, make_supplier, make_material
):
    """If the LLM returns action="match" with a material_id that was not
    among the candidates shown to it, the decision must be downgraded to
    action="new" rather than trusted as-is — see ADR-0019 final review
    Finding 3. Trusting a hallucinated id would write a dangling FK and
    fail the whole batch's db.commit()."""
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    candidate = make_material(canonical_name="Candidate Material")
    candidate.embedding = [0.5] * 1536
    session.commit()

    line = _line(raw_name="New Raw Name")
    hallucinated_decision = MatchDecision(
        action="match",
        material_id=uuid.uuid4(),
        confidence=0.9,
        reasoning="matches by attributes",
        suggested_internal_sku=None,
    )

    with patch(
        "app.price_ingestion.matching.embed_text", return_value=[0.5] * 1536
    ), patch(
        "app.price_ingestion.matching._decide_match", return_value=hallucinated_decision
    ):
        results = match_price_list_lines(session, supplier.id, [line])

    assert len(results) == 1
    assert results[0].decision.action == "new"
    assert results[0].decision.material_id is None
    assert "matches by attributes" in results[0].decision.reasoning
