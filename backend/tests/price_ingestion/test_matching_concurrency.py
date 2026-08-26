"""Tests for ADR-0022: early chunk-overlap dedup (skip expensive matching
call for lines grouped with an earlier representative) and parallel
matching (ThreadPoolExecutor for _decide_match/embed_text, retry/backoff
isolation per line) — see docs/decisions/0022-price-list-matching-dedup-and-concurrency.md.
"""

import threading
import time
from unittest.mock import patch

import httpx
from openai import RateLimitError

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


def _rate_limit_error():
    request = httpx.Request("POST", "https://api.openai.com/v1/x")
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _decision(**overrides):
    defaults = dict(
        action="new",
        material_id=None,
        confidence=0.8,
        reasoning="no close match found",
        suggested_internal_sku="NEW-SKU-1",
    )
    defaults.update(overrides)
    return MatchDecision(**defaults)


class TestEarlyDedup:
    def test_second_of_two_identical_lines_on_same_page_inherits_decision_without_own_call(
        self, db_session, make_supplier
    ):
        """ADR-0023: grouping is by page_number + exact raw_name match, not
        embedding distance. Two lines on the same overlap page with
        identical (normalized) text must group; the follower skips its own
        _decide_match call and inherits the representative's decision."""
        session, _material_ids, _supplier_ids = db_session
        supplier = make_supplier()

        line_a = _line(raw_name="Screen Type A", page_number=3)
        line_b = _line(raw_name="  screen type a  ", page_number=3)

        embedding_a = [1.0] + [0.0] * 1535
        embedding_b = [0.99] + [0.01] * 1535
        decision = _decision(reasoning="looks new")

        with patch(
            "app.price_ingestion.matching.embed_text",
            side_effect=[embedding_a, embedding_b],
        ) as mock_embed, patch(
            "app.price_ingestion.matching._decide_match", return_value=decision
        ) as mock_llm:
            results = match_price_list_lines(session, supplier.id, [line_a, line_b])

        # embed_text is still called once per line (used later for
        # post-match new-line dedup, ADR-0019 §4) but _decide_match must be
        # called only once — the follower reuses the representative's
        # decision instead of making its own LLM call.
        assert mock_embed.call_count == 2
        mock_llm.assert_called_once()

        assert len(results) == 2
        assert results[0].decision.action == "new"
        assert results[1].decision.action == "new"
        assert results[1].decision.reasoning != results[0].decision.reasoning
        assert "унаследовано от строки-представителя" in results[1].decision.reasoning
        assert results[1].possible_duplicate_of == [0]

    def test_two_lines_with_different_text_same_page_each_make_their_own_call(
        self, db_session, make_supplier
    ):
        session, _material_ids, _supplier_ids = db_session
        supplier = make_supplier()

        line_a = _line(raw_name="Screen Type A", page_number=3)
        line_b = _line(raw_name="Completely Different Item", page_number=3)

        embedding_a = [1.0] + [0.0] * 1535
        embedding_b = [0.0, 1.0] + [0.0] * 1534

        with patch(
            "app.price_ingestion.matching.embed_text",
            side_effect=[embedding_a, embedding_b],
        ) as mock_embed, patch(
            "app.price_ingestion.matching._decide_match",
            side_effect=[_decision(reasoning="a"), _decision(reasoning="b")],
        ) as mock_llm:
            results = match_price_list_lines(session, supplier.id, [line_a, line_b])

        assert mock_embed.call_count == 2
        assert mock_llm.call_count == 2
        assert results[0].decision.reasoning == "a"
        assert results[1].decision.reasoning == "b"

    def test_identical_text_on_different_pages_each_make_their_own_call(
        self, db_session, make_supplier
    ):
        """Two lines with identical text but NOT sharing a page cannot be a
        chunk-overlap duplicate of each other (ADR-0023) — each must still
        make its own _decide_match call."""
        session, _material_ids, _supplier_ids = db_session
        supplier = make_supplier()

        line_a = _line(raw_name="Screen Type A", page_number=2)
        line_b = _line(raw_name="Screen Type A", page_number=9)

        embedding_a = [1.0] + [0.0] * 1535
        embedding_b = [0.99] + [0.01] * 1535

        with patch(
            "app.price_ingestion.matching.embed_text",
            side_effect=[embedding_a, embedding_b],
        ), patch(
            "app.price_ingestion.matching._decide_match",
            side_effect=[_decision(reasoning="a"), _decision(reasoning="b")],
        ) as mock_llm:
            results = match_price_list_lines(session, supplier.id, [line_a, line_b])

        assert mock_llm.call_count == 2
        assert results[0].decision.reasoning == "a"
        assert results[1].decision.reasoning == "b"


class TestConcurrentOrdering:
    def test_results_preserve_input_order_regardless_of_thread_completion_order(
        self, db_session, make_supplier
    ):
        session, _material_ids, _supplier_ids = db_session
        supplier = make_supplier()

        lines = [_line(raw_name=f"Distinct Item {i}") for i in range(8)]
        # Orthogonal-ish embeddings so nothing groups as a duplicate.
        embeddings = []
        for i in range(8):
            vec = [0.0] * 1536
            vec[i] = 1.0
            embeddings.append(vec)

        # Slower calls for earlier lines, faster for later ones, so thread
        # completion order is reversed relative to input order.
        def _delayed_decide(raw_name, raw_sku, candidates):
            index = int(raw_name.rsplit(" ", 1)[1])
            time.sleep((8 - index) * 0.01)
            return _decision(reasoning=f"decision for {index}")

        with patch(
            "app.price_ingestion.matching.embed_text", side_effect=embeddings
        ), patch(
            "app.price_ingestion.matching._decide_match", side_effect=_delayed_decide
        ):
            results = match_price_list_lines(session, supplier.id, lines)

        assert [r.decision.reasoning for r in results] == [
            f"decision for {i}" for i in range(8)
        ]


class TestRetryIsolation:
    def test_rate_limit_exhausted_on_one_line_marks_failed_others_unaffected(
        self, db_session, make_supplier
    ):
        session, _material_ids, _supplier_ids = db_session
        supplier = make_supplier()

        line_a = _line(raw_name="Line A")
        line_b = _line(raw_name="Line B (always rate limited)")
        line_c = _line(raw_name="Line C")

        embeddings = [
            [1.0, 0.0] + [0.0] * 1534,
            [0.0, 1.0] + [0.0] * 1534,
            [0.0, 0.0, 1.0] + [0.0] * 1533,
        ]

        def _decide(raw_name, raw_sku, candidates):
            if raw_name == "Line B (always rate limited)":
                raise _rate_limit_error()
            return _decision(reasoning=f"ok:{raw_name}")

        with patch(
            "app.price_ingestion.matching.embed_text", side_effect=embeddings
        ), patch(
            "app.price_ingestion.matching._decide_match", side_effect=_decide
        ), patch("app.price_ingestion.retry.time.sleep"):
            results = match_price_list_lines(session, supplier.id, [line_a, line_b, line_c])

        assert len(results) == 3
        assert results[0].processing_status is None
        assert results[0].decision.reasoning == "ok:Line A"
        assert results[1].processing_status == "failed"
        assert results[2].processing_status is None
        assert results[2].decision.reasoning == "ok:Line C"

    def test_rate_limit_succeeds_on_third_attempt_not_marked_failed(
        self, db_session, make_supplier
    ):
        session, _material_ids, _supplier_ids = db_session
        supplier = make_supplier()

        line = _line(raw_name="Flaky Line")
        embedding = [1.0] + [0.0] * 1535

        attempts = {"count": 0}

        def _decide(raw_name, raw_sku, candidates):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise _rate_limit_error()
            return _decision(reasoning="succeeded eventually")

        with patch(
            "app.price_ingestion.matching.embed_text", return_value=embedding
        ), patch(
            "app.price_ingestion.matching._decide_match", side_effect=_decide
        ), patch("app.price_ingestion.retry.time.sleep"):
            results = match_price_list_lines(session, supplier.id, [line])

        assert results[0].processing_status is None
        assert results[0].decision.reasoning == "succeeded eventually"
        assert attempts["count"] == 3


class TestEarlyDedupInteractsWithRetryFailure:
    def test_follower_of_a_failed_representative_is_also_marked_failed(
        self, db_session, make_supplier
    ):
        """If the representative's retry is exhausted, a follower that
        inherited its decision has nothing valid to inherit — it must be
        marked processing_status="failed" too, not silently presented as
        a normal action="new" decision."""
        session, _material_ids, _supplier_ids = db_session
        supplier = make_supplier()

        line_a = _line(raw_name="Screen Type A", page_number=3)
        line_b = _line(raw_name="screen type a", page_number=3)

        embedding_a = [1.0] + [0.0] * 1535
        embedding_b = [0.99] + [0.01] * 1535

        def _always_rate_limited(raw_name, raw_sku, candidates):
            raise _rate_limit_error()

        with patch(
            "app.price_ingestion.matching.embed_text",
            side_effect=[embedding_a, embedding_b],
        ), patch(
            "app.price_ingestion.matching._decide_match",
            side_effect=_always_rate_limited,
        ), patch("app.price_ingestion.retry.time.sleep"):
            results = match_price_list_lines(session, supplier.id, [line_a, line_b])

        assert results[0].processing_status == "failed"
        assert results[1].processing_status == "failed"


class TestDbCallsStayOnMainThread:
    def test_alias_and_candidate_lookups_only_happen_from_main_thread(
        self, db_session, make_supplier, make_material
    ):
        session, _material_ids, _supplier_ids = db_session
        supplier = make_supplier()
        candidate = make_material(canonical_name="Candidate Material")
        candidate.embedding = [0.5] * 1536
        session.commit()

        main_thread_id = threading.get_ident()
        recorded_threads = []

        original_execute = session.execute

        def _tracking_execute(*args, **kwargs):
            recorded_threads.append(threading.get_ident())
            return original_execute(*args, **kwargs)

        lines = [_line(raw_name=f"Unique Item {i}") for i in range(4)]
        embeddings = []
        for i in range(4):
            vec = [0.0] * 1536
            vec[i] = 1.0
            embeddings.append(vec)

        with patch.object(session, "execute", side_effect=_tracking_execute), patch(
            "app.price_ingestion.matching.embed_text", side_effect=embeddings
        ), patch(
            "app.price_ingestion.matching._decide_match",
            return_value=_decision(action="new"),
        ):
            match_price_list_lines(session, supplier.id, lines)

        assert recorded_threads, "expected db.execute to be called at least once"
        assert all(t == main_thread_id for t in recorded_threads)
