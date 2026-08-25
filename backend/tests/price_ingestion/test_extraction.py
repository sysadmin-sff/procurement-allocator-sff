"""Tests for app.price_ingestion.extraction (step 1, ADR-0019 §3) — pure
extraction, no matching. OpenAI call always mocked."""

from unittest.mock import MagicMock, patch

import pytest

from app.price_ingestion.extraction import (
    ExtractedPriceLine,
    PriceIngestionError,
    UnsupportedFileTypeError,
    extract_price_list_lines,
    validate_content_type,
)

FAKE_PDF_BYTES = b"%PDF-1.4 fake price list"


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
        )
    ]
    with _mock_parse(lines):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = "fake-key"
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
            mock_settings.openai_api_key = "fake-key"
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            with pytest.raises(PriceIngestionError):
                extract_price_list_lines(
                    file_bytes=FAKE_PDF_BYTES, content_type="application/pdf"
                )


def test_extract_returns_empty_list_when_model_finds_nothing():
    with _mock_parse([]):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = "fake-key"
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            result = extract_price_list_lines(
                file_bytes=FAKE_PDF_BYTES, content_type="application/pdf"
            )
    assert result == []
