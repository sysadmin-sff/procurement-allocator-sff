"""Tests for app.price_ingestion.matching — see ADR-0019 §2/§4, ADR-0025.

Alias short-circuit must skip the LLM call entirely (asserted via
mock.assert_not_called). The normal path mocks _decide_match only — there
is no embedding/vector-search step left in this path at all (ADR-0025 §1);
tests assert find_top_candidates/embed_text are never called to prove that.
"""

import logging
import uuid
from unittest.mock import patch

from app.models import SupplierMaterialAlias
from app.price_ingestion.extraction import ExtractedPriceLine
from app.price_ingestion.matching import MatchDecision, match_price_list_lines


def _line(raw_name="Some Material", price=10.0, raw_sku=None, page_number=1):
    return ExtractedPriceLine(
        raw_name=raw_name,
        raw_sku=raw_sku,
        price=price,
        currency="USD",
        availability=None,
        min_order_qty=None,
        page_number=page_number,
    )


def test_known_alias_skips_llm_entirely(db_session, make_supplier, make_material):
    session, _material_ids, _supplier_ids, _user_ids = db_session
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

    with patch("app.price_ingestion.matching._decide_match") as mock_llm, patch(
        "app.price_ingestion.candidates.find_top_candidates"
    ) as mock_candidates, patch("app.price_ingestion.embeddings.embed_text") as mock_embed:
        results = match_price_list_lines(session, supplier.id, [line])

    mock_llm.assert_not_called()
    mock_candidates.assert_not_called()
    mock_embed.assert_not_called()
    assert len(results) == 1
    assert results[0].decision.action == "match"
    assert results[0].decision.material_id == material.id
    assert results[0].decision.confidence == 1.0
    assert results[0].decision.reasoning == "known alias"


def test_unknown_line_goes_through_llm_against_full_catalog_no_vector_search(
    db_session, make_supplier, make_material
):
    """ADR-0025 §1: no vector prefiltering step exists in this path at all
    — _decide_match must be called with the full Material list, and
    find_top_candidates/embed_text must never be called from matching."""
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    candidate = make_material(canonical_name="Candidate Material")
    other = make_material(canonical_name="Other Material")
    session.commit()

    line = _line(raw_name="New Raw Name")
    fake_decision = MatchDecision(
        action="match",
        material_id=candidate.id,
        confidence=0.9,
        reasoning="matches by name",
    )

    with patch(
        "app.price_ingestion.matching._decide_match", return_value=fake_decision
    ) as mock_llm, patch(
        "app.price_ingestion.candidates.find_top_candidates"
    ) as mock_candidates, patch("app.price_ingestion.embeddings.embed_text") as mock_embed:
        results = match_price_list_lines(session, supplier.id, [line])

    mock_candidates.assert_not_called()
    mock_embed.assert_not_called()
    mock_llm.assert_called_once()
    call_args = mock_llm.call_args.args
    passed_candidates = call_args[2]
    passed_ids = {m.id for m in passed_candidates}
    assert candidate.id in passed_ids
    assert other.id in passed_ids

    assert results[0].decision.action == "match"
    assert results[0].decision.material_id == candidate.id


def test_not_found_decision_is_kept_as_is(db_session, make_supplier, make_material):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    make_material(canonical_name="Unrelated Material")
    session.commit()

    line = _line(raw_name="Nothing Like It")
    decision_not_found = MatchDecision(
        action="not_found",
        material_id=None,
        confidence=0.9,
        reasoning="no candidate resembles this line",
    )

    with patch(
        "app.price_ingestion.matching._decide_match", return_value=decision_not_found
    ):
        results = match_price_list_lines(session, supplier.id, [line])

    assert results[0].decision.action == "not_found"
    assert results[0].decision.material_id is None


def test_not_found_high_confidence_logs_structured_warning(
    db_session, make_supplier, caplog
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()

    line = _line(raw_name="Mystery Line")
    decision_not_found = MatchDecision(
        action="not_found",
        material_id=None,
        confidence=0.65,
        reasoning="close but no exact match",
    )

    with patch(
        "app.price_ingestion.matching._decide_match", return_value=decision_not_found
    ), caplog.at_level(logging.INFO, logger="app.price_ingestion.matching"):
        match_price_list_lines(session, supplier.id, [line])

    assert any(
        "not_found" in record.message and "Mystery Line" in record.message
        for record in caplog.records
    )


def test_not_found_low_confidence_does_not_log(db_session, make_supplier, caplog):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()

    line = _line(raw_name="Totally Unrelated Line")
    decision_not_found = MatchDecision(
        action="not_found",
        material_id=None,
        confidence=0.1,
        reasoning="nothing close",
    )

    with patch(
        "app.price_ingestion.matching._decide_match", return_value=decision_not_found
    ), caplog.at_level(logging.INFO, logger="app.price_ingestion.matching"):
        match_price_list_lines(session, supplier.id, [line])

    assert not any("not_found" in record.message for record in caplog.records)


def test_two_match_lines_on_same_material_id_flag_each_other_as_duplicates(
    db_session, make_supplier, make_material
):
    """ADR-0021 final clarification: page-overlap chunking can cause two
    chunks to independently produce action="match" lines for the same
    material_id. _flag_duplicate_lines must catch this symmetrically to how
    it already catches action="new" duplicates (exact material_id match,
    not cosine distance — no need to measure similarity when the id is
    identical)."""
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    candidate = make_material()
    session.commit()

    line_a = _line(raw_name="Duplicated Match Line")
    line_b = _line(raw_name="Duplicated Match Line")

    decision_match = MatchDecision(
        action="match", material_id=candidate.id, confidence=0.9, reasoning="matches",
    )

    with patch(
        "app.price_ingestion.matching._decide_match",
        side_effect=[decision_match, decision_match],
    ):
        results = match_price_list_lines(session, supplier.id, [line_a, line_b])

    assert results[0].possible_duplicate_of == [1]
    assert results[1].possible_duplicate_of == [0]


def test_match_lines_on_different_material_ids_do_not_flag_each_other(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    candidate_a = make_material()
    candidate_b = make_material()
    session.commit()

    line_a = _line(raw_name="Line A")
    line_b = _line(raw_name="Line B")

    decision_a = MatchDecision(
        action="match", material_id=candidate_a.id, confidence=0.9, reasoning="matches a",
    )
    decision_b = MatchDecision(
        action="match", material_id=candidate_b.id, confidence=0.9, reasoning="matches b",
    )

    with patch(
        "app.price_ingestion.matching._decide_match",
        side_effect=[decision_a, decision_b],
    ):
        results = match_price_list_lines(session, supplier.id, [line_a, line_b])

    assert results[0].possible_duplicate_of == []
    assert results[1].possible_duplicate_of == []


def test_known_alias_duplicate_match_lines_are_flagged_too(
    db_session, make_supplier, make_material
):
    """Known-alias short-circuit lines (ADR-0019 §2) still carry
    action="match" + material_id. Two lines with identical raw_name (the
    likely real-world case for chunk-overlap duplicates of an
    already-known material) each independently hit the alias table (no
    LLM call either way — ADR-0022 §1 early dedup is currently disabled,
    see EARLY_DEDUP_ENABLED in matching.py, so there is no
    representative/follower inheritance here). Both end up action="match"
    on the same material_id and are flagged as duplicates by the existing
    post-match dedup (ADR-0021 §3)."""
    session, _material_ids, _supplier_ids, _user_ids = db_session
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

    line_a = _line(raw_name="Known Raw Name")
    line_b = _line(raw_name="Known Raw Name")

    with patch("app.price_ingestion.matching._decide_match") as mock_llm:
        results = match_price_list_lines(session, supplier.id, [line_a, line_b])

    mock_llm.assert_not_called()
    assert results[0].decision.action == "match"
    assert results[0].decision.material_id == material.id
    assert results[1].decision.action == "match"
    assert results[1].decision.material_id == material.id
    assert results[0].possible_duplicate_of == [1]
    assert results[1].possible_duplicate_of == [0]


def test_hallucinated_material_id_is_downgraded_to_not_found(
    db_session, make_supplier, make_material
):
    """If the LLM returns action="match" with a material_id that was not
    among the candidates shown to it, the decision must be downgraded to
    action="not_found" rather than trusted as-is — see ADR-0019 final
    review Finding 3, updated by ADR-0025 §3 (there is no "new" action to
    downgrade to any more). Trusting a hallucinated id would write a
    dangling FK and fail the whole batch's db.commit()."""
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    make_material(canonical_name="Candidate Material")
    session.commit()

    line = _line(raw_name="New Raw Name")
    hallucinated_decision = MatchDecision(
        action="match",
        material_id=uuid.uuid4(),
        confidence=0.9,
        reasoning="matches by attributes",
    )

    with patch(
        "app.price_ingestion.matching._decide_match", return_value=hallucinated_decision
    ):
        results = match_price_list_lines(session, supplier.id, [line])

    assert len(results) == 1
    assert results[0].decision.action == "not_found"
    assert results[0].decision.material_id is None
    assert "matches by attributes" in results[0].decision.reasoning
