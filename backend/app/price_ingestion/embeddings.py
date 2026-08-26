"""Embeddings client for price-list matching — see ADR-0019 §1.

Used by Material create/update (graceful degradation on failure — the
caller decides what "failure" means for its own contract), the one-time
backfill script, and price_ingestion matching's candidate search and
duplicate-detection.
"""

from __future__ import annotations

import json

from openai import APIError, APITimeoutError, OpenAI

from app.core.config import settings


class EmbeddingError(Exception):
    """OpenAI embeddings API unreachable, timed out, errored, or no API key
    configured. Callers decide how to degrade — see ADR-0019 §1 (Material
    create/update swallow this; the backfill script and price_ingestion
    matching do not, since they have no "existing value" to fall back to)."""


def material_embedding_input(canonical_name: str, attributes: dict) -> str:
    """canonical_name + serialized attributes — see ADR-0019 §1, "Входной
    текст для эмбеддинга". Same function used everywhere an embedding input
    is built so create/update/backfill/matching never drift apart."""
    if not attributes:
        return canonical_name
    return f"{canonical_name} {json.dumps(attributes, sort_keys=True)}"


def embed_text(text: str) -> list[float]:
    """One OpenAI embeddings call. Raises EmbeddingError on any failure —
    never lets the raw OpenAI exception or a missing API key surface past
    this module."""
    if not settings.openai_api_key:
        raise EmbeddingError("OpenAI API не настроен (отсутствует OPENAI_API_KEY)")

    client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
    try:
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=text,
        )
    except (APIError, APITimeoutError) as exc:
        raise EmbeddingError(f"Embeddings API call failed: {exc}") from exc

    return list(response.data[0].embedding)
