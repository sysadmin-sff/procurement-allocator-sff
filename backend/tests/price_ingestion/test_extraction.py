"""Tests for app.price_ingestion.extraction (step 1, ADR-0019 §3) — pure
extraction, no matching. OpenAI call always mocked."""

import base64
import io
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import RateLimitError
from pydantic import SecretStr
from pypdf import PdfReader, PdfWriter

from app.price_ingestion.extraction import (
    ExtractedPriceLine,
    PriceIngestionError,
    UnsupportedFileTypeError,
    _page_chunks,
    extract_price_list_lines,
    validate_content_type,
)


def _make_pdf_bytes(num_pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _rate_limit_error():
    request = httpx.Request("POST", "https://api.openai.com/v1/x")
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


FAKE_PDF_BYTES = _make_pdf_bytes(1)


def test_validate_content_type_accepts_pdf():
    validate_content_type("application/pdf")


def test_validate_content_type_rejects_unsupported():
    with pytest.raises(UnsupportedFileTypeError):
        validate_content_type("text/plain")


def _mock_parse(lines):
    mock_response = MagicMock()
    mock_response.output_parsed = MagicMock(lines=lines)
    mock_client = MagicMock()
    mock_client.responses.parse.return_value = mock_response
    return patch("app.price_ingestion.extraction.OpenAI", return_value=mock_client)


def test_extract_returns_parsed_lines():
    lines = [
        ExtractedPriceLine(
            raw_name="Fiberglass Screen 18x14",
            raw_sku="FS-1814",
            price=5.10,
            currency="USD",
            availability=100,
            min_order_qty=1,
            page_number=1,
        )
    ]
    with _mock_parse(lines):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = SecretStr("fake-key")
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            result = extract_price_list_lines(
                file_bytes=FAKE_PDF_BYTES, content_type="application/pdf"
            )
    assert result == lines


def test_extract_raises_price_ingestion_error_when_api_key_missing():
    with patch("app.price_ingestion.extraction.settings") as mock_settings:
        mock_settings.openai_api_key = None
        with pytest.raises(PriceIngestionError):
            extract_price_list_lines(
                file_bytes=FAKE_PDF_BYTES, content_type="application/pdf"
            )


def test_extract_raises_price_ingestion_error_on_api_failure():
    from openai import APIError

    mock_client = MagicMock()
    mock_client.responses.parse.side_effect = APIError(
        "boom", request=MagicMock(), body=None
    )
    with patch("app.price_ingestion.extraction.OpenAI", return_value=mock_client):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = SecretStr("fake-key")
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            with pytest.raises(PriceIngestionError):
                extract_price_list_lines(
                    file_bytes=FAKE_PDF_BYTES, content_type="application/pdf"
                )


def test_extract_returns_empty_list_when_model_finds_nothing():
    with _mock_parse([]):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = SecretStr("fake-key")
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            result = extract_price_list_lines(
                file_bytes=FAKE_PDF_BYTES, content_type="application/pdf"
            )
    assert result == []


def test_page_chunks_splits_multipage_document_with_one_page_overlap():
    # 10 pages, 3 pages/chunk, 1-page overlap (ADR-0021 §1/§3):
    # chunk N's last page == chunk N+1's first page.
    chunks = _page_chunks(total_pages=10, pages_per_chunk=3)
    assert chunks == [
        (0, 2),
        (2, 4),
        (4, 6),
        (6, 8),
        (8, 9),
    ]


def test_page_chunks_single_chunk_when_document_fits():
    # 2 pages, chunk size 3 — whole document is one chunk (no overlap to add).
    chunks = _page_chunks(total_pages=2, pages_per_chunk=3)
    assert chunks == [(0, 1)]


def test_page_chunks_exact_multiple_of_chunk_size():
    chunks = _page_chunks(total_pages=6, pages_per_chunk=3)
    assert chunks == [(0, 2), (2, 4), (4, 5)]


def test_multipage_pdf_makes_one_call_per_chunk_and_concatenates_in_order():
    # 7 pages / 3 per chunk (default) with 1-page overlap -> chunks
    # (0,2), (2,4), (4,6) = 3 calls, each returning its own lines. Calls
    # now run concurrently (EXTRACTION_CONCURRENCY) — the response is
    # selected by reading the chunk's page range out of the request
    # itself (not by call order, which a thread pool does not guarantee)
    # so this test is robust to whichever order the pool's threads
    # actually complete in.
    pdf_bytes = _make_pdf_bytes(7)

    chunk_lines_by_start_page = {
        1: [ExtractedPriceLine(
            raw_name="Item chunk 0", raw_sku=None, price=1.0,
            currency="USD", availability=None, min_order_qty=None, page_number=1,
        )],
        3: [ExtractedPriceLine(
            raw_name="Item chunk 1", raw_sku=None, price=1.0,
            currency="USD", availability=None, min_order_qty=None, page_number=3,
        )],
        5: [ExtractedPriceLine(
            raw_name="Item chunk 2", raw_sku=None, price=1.0,
            currency="USD", availability=None, min_order_qty=None, page_number=5,
        )],
    }

    mock_client = MagicMock()

    def _fake_parse(**kwargs):
        prompt_text = kwargs["input"][0]["content"][0]["text"]
        # start_page is the first number in "страницы {start}-{end}"
        start_page = int(prompt_text.split("страницы ")[1].split("-")[0])
        mock_response = MagicMock()
        mock_response.output_parsed = MagicMock(lines=chunk_lines_by_start_page[start_page])
        return mock_response

    mock_client.responses.parse.side_effect = _fake_parse

    with patch("app.price_ingestion.extraction.OpenAI", return_value=mock_client):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = SecretStr("fake-key")
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            result = extract_price_list_lines(
                file_bytes=pdf_bytes, content_type="application/pdf"
            )

    assert mock_client.responses.parse.call_count == 3
    assert result == [
        chunk_lines_by_start_page[1][0],
        chunk_lines_by_start_page[3][0],
        chunk_lines_by_start_page[5][0],
    ]


def test_result_order_matches_chunk_order_regardless_of_thread_completion_order():
    # Same 3-chunk document, but chunk 0's call is deliberately the
    # slowest and chunk 2's the fastest — thread completion order is
    # reversed relative to chunk order. The result must still be
    # concatenated in chunk order (pool.map preserves input order in its
    # return value; concatenation must not reorder based on which thread
    # finished first).
    pdf_bytes = _make_pdf_bytes(7)

    def _fake_parse(**kwargs):
        prompt_text = kwargs["input"][0]["content"][0]["text"]
        start_page = int(prompt_text.split("страницы ")[1].split("-")[0])
        chunk_index = {1: 0, 3: 1, 5: 2}[start_page]
        # Reverse-order delay: chunk 0 slowest, chunk 2 fastest.
        time.sleep((3 - chunk_index) * 0.05)
        mock_response = MagicMock()
        mock_response.output_parsed = MagicMock(lines=[
            ExtractedPriceLine(
                raw_name=f"Item chunk {chunk_index}", raw_sku=None, price=1.0,
                currency="USD", availability=None, min_order_qty=None,
                page_number=start_page,
            )
        ])
        return mock_response

    mock_client = MagicMock()
    mock_client.responses.parse.side_effect = _fake_parse

    with patch("app.price_ingestion.extraction.OpenAI", return_value=mock_client):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = SecretStr("fake-key")
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            result = extract_price_list_lines(
                file_bytes=pdf_bytes, content_type="application/pdf"
            )

    assert [line.raw_name for line in result] == [
        "Item chunk 0", "Item chunk 1", "Item chunk 2",
    ]


def test_one_chunk_exhausting_retries_fails_the_whole_extraction():
    # Unlike matching's per-line isolation (ADR-0022 §2), a chunk has no
    # safe partial-result placeholder — a lost page range would silently
    # hide missing lines from the review screen. One chunk's exhausted
    # retries must fail extract_price_list_lines entirely, not degrade to
    # a partial result.
    pdf_bytes = _make_pdf_bytes(7)

    def _fake_parse(**kwargs):
        prompt_text = kwargs["input"][0]["content"][0]["text"]
        start_page = int(prompt_text.split("страницы ")[1].split("-")[0])
        if start_page == 3:
            raise _rate_limit_error()
        mock_response = MagicMock()
        mock_response.output_parsed = MagicMock(lines=[])
        return mock_response

    mock_client = MagicMock()
    mock_client.responses.parse.side_effect = _fake_parse

    with patch("app.price_ingestion.extraction.OpenAI", return_value=mock_client):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = SecretStr("fake-key")
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            with patch("app.price_ingestion.retry.time.sleep"):
                with pytest.raises(PriceIngestionError):
                    extract_price_list_lines(
                        file_bytes=pdf_bytes, content_type="application/pdf"
                    )


def test_chunk_call_retries_on_rate_limit_then_succeeds():
    # A chunk whose first two attempts hit RateLimitError must still
    # succeed on the third (ADR-0022 §2 retry/backoff, MAX_ATTEMPTS=3) —
    # proves RateLimitError actually reaches call_with_retry rather than
    # being pre-mapped to PriceIngestionError before retry can see it.
    pdf_bytes = _make_pdf_bytes(2)  # single chunk, simplest case
    attempts = {"count": 0}

    def _fake_parse(**kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _rate_limit_error()
        mock_response = MagicMock()
        mock_response.output_parsed = MagicMock(lines=[
            ExtractedPriceLine(
                raw_name="Recovered item", raw_sku=None, price=1.0,
                currency="USD", availability=None, min_order_qty=None, page_number=1,
            )
        ])
        return mock_response

    mock_client = MagicMock()
    mock_client.responses.parse.side_effect = _fake_parse

    with patch("app.price_ingestion.extraction.OpenAI", return_value=mock_client):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = SecretStr("fake-key")
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            with patch("app.price_ingestion.retry.time.sleep"):
                result = extract_price_list_lines(
                    file_bytes=pdf_bytes, content_type="application/pdf"
                )

    assert attempts["count"] == 3
    assert result[0].raw_name == "Recovered item"


def test_document_fitting_in_one_chunk_makes_a_single_call():
    # 2 pages, default chunk size 3 -> one chunk, no extra machinery.
    pdf_bytes = _make_pdf_bytes(2)
    lines = [
        ExtractedPriceLine(
            raw_name="Only item", raw_sku=None, price=2.0,
            currency="USD", availability=None, min_order_qty=None,
            page_number=1,
        )
    ]
    with _mock_parse(lines) as mock_openai:
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = SecretStr("fake-key")
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            result = extract_price_list_lines(
                file_bytes=pdf_bytes, content_type="application/pdf"
            )

    mock_openai.return_value.responses.parse.assert_called_once()
    assert result == lines


def test_single_chunk_pdf_prompt_carries_absolute_page_range():
    # 2 pages, one chunk -> prompt must tell the model "pages 1-2", not a
    # relative/unanchored range (ADR-0023: absolute numbering is passed
    # explicitly, not inferred by the model from the fragment).
    pdf_bytes = _make_pdf_bytes(2)
    with _mock_parse([]) as mock_openai:
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = SecretStr("fake-key")
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            extract_price_list_lines(file_bytes=pdf_bytes, content_type="application/pdf")

    call_kwargs = mock_openai.return_value.responses.parse.call_args.kwargs
    prompt_text = call_kwargs["input"][0]["content"][0]["text"]
    assert "1" in prompt_text and "2" in prompt_text


def test_multipage_pdf_each_chunk_call_contains_correct_pages():
    # 7 pages / 3 per chunk with 1-page overlap -> page ranges
    # (0,2), (2,4), (4,6): sizes 3, 3, 3 pages respectively.
    pdf_bytes = _make_pdf_bytes(7)
    expected_page_counts = [3, 3, 3]

    mock_client = MagicMock()
    captured_page_counts = []

    def _fake_parse(**kwargs):
        file_content = kwargs["input"][0]["content"][1]
        data_url = file_content["file_data"]
        b64_data = data_url.split(",", 1)[1]
        pdf_data = base64.b64decode(b64_data)
        captured_page_counts.append(len(PdfReader(io.BytesIO(pdf_data)).pages))
        mock_response = MagicMock()
        mock_response.output_parsed = MagicMock(lines=[])
        return mock_response

    mock_client.responses.parse.side_effect = _fake_parse

    with patch("app.price_ingestion.extraction.OpenAI", return_value=mock_client):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = SecretStr("fake-key")
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            extract_price_list_lines(file_bytes=pdf_bytes, content_type="application/pdf")

    assert captured_page_counts == expected_page_counts


def test_input_image_is_not_chunked():
    # input_image responses don't ask the model for page_number (single
    # page, no ambiguity) — the mocked line has no page_number field, and
    # extract_price_list_lines must fill in page_number=1 itself.
    mock_line = MagicMock(
        raw_name="Scanned item", raw_sku=None, price=3.0,
        currency="USD", availability=None, min_order_qty=None,
    )
    mock_line.model_dump.return_value = {
        "raw_name": "Scanned item", "raw_sku": None, "price": 3.0,
        "currency": "USD", "availability": None, "min_order_qty": None,
    }
    with _mock_parse([mock_line]) as mock_openai:
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = SecretStr("fake-key")
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            result = extract_price_list_lines(
                file_bytes=b"not-a-real-image-but-never-parsed-as-pdf",
                content_type="image/png",
            )

    mock_openai.return_value.responses.parse.assert_called_once()
    assert result == [
        ExtractedPriceLine(
            raw_name="Scanned item", raw_sku=None, price=3.0,
            currency="USD", availability=None, min_order_qty=None,
            page_number=1,
        )
    ]
