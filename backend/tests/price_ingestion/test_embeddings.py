"""Tests for app.price_ingestion.embeddings — see ADR-0019 §1.

embed_text always mocks the OpenAI client (no real API calls in this
suite) — this file only tests input serialization and error handling.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.price_ingestion.embeddings import (
    EmbeddingError,
    embed_text,
    material_embedding_input,
)


def test_material_embedding_input_combines_name_and_attributes():
    text = material_embedding_input(
        "84 in. 18x14 Fiberglass Screen", {"width_in": 84, "mesh": "18x14"}
    )
    assert "84 in. 18x14 Fiberglass Screen" in text
    assert "width_in" in text
    assert "84" in text


def test_material_embedding_input_handles_empty_attributes():
    text = material_embedding_input("Aluminum Frame Track", {})
    assert text.startswith("Aluminum Frame Track")


def _mock_openai_embeddings(vector):
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=vector)]
    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_response
    return patch("app.price_ingestion.embeddings.OpenAI", return_value=mock_client)


def test_embed_text_returns_vector_from_openai():
    fake_vector = [0.01] * 1536
    with _mock_openai_embeddings(fake_vector):
        with patch("app.price_ingestion.embeddings.settings") as mock_settings:
            mock_settings.openai_api_key = "fake-key"
            mock_settings.openai_embedding_model = "text-embedding-3-small"
            result = embed_text("some material text")
    assert result == fake_vector


def test_embed_text_raises_embedding_error_when_api_key_missing():
    with patch("app.price_ingestion.embeddings.settings") as mock_settings:
        mock_settings.openai_api_key = None
        with pytest.raises(EmbeddingError):
            embed_text("some material text")


def test_embed_text_raises_embedding_error_on_api_failure():
    from openai import APIError

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = APIError(
        "boom", request=MagicMock(), body=None
    )
    with patch("app.price_ingestion.embeddings.OpenAI", return_value=mock_client):
        with patch("app.price_ingestion.embeddings.settings") as mock_settings:
            mock_settings.openai_api_key = "fake-key"
            mock_settings.openai_embedding_model = "text-embedding-3-small"
            with pytest.raises(EmbeddingError):
                embed_text("some material text")
