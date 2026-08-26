"""Tests for the one-time backfill script — see ADR-0019 §1.

Idempotent: only touches Material rows with embedding IS NULL.
"""

from unittest.mock import patch

from app.scripts.backfill_material_embeddings import run_backfill


def test_backfill_embeds_materials_with_null_embedding(db_session, make_material):
    session, _material_ids, _user_ids = db_session
    material = make_material(canonical_name="Needs Embedding")
    assert material.embedding is None

    with patch(
        "app.scripts.backfill_material_embeddings.embed_text",
        return_value=[0.4] * 1536,
    ):
        count = run_backfill(session)

    session.refresh(material)
    assert count >= 1
    assert material.embedding is not None
    assert len(material.embedding) == 1536


def test_backfill_does_not_touch_materials_with_existing_embedding(
    db_session, make_material
):
    session, _material_ids, _user_ids = db_session
    material = make_material(canonical_name="Already Embedded")
    material.embedding = [0.9] * 1536
    session.commit()

    with patch(
        "app.scripts.backfill_material_embeddings.embed_text"
    ) as mock_embed:
        run_backfill(session)

    mock_embed.assert_not_called()
    session.refresh(material)
    assert material.embedding == [0.9] * 1536


def test_backfill_is_idempotent_on_second_run(db_session, make_material):
    session, _material_ids, _user_ids = db_session
    make_material(canonical_name="Needs Embedding Twice")

    with patch(
        "app.scripts.backfill_material_embeddings.embed_text",
        return_value=[0.4] * 1536,
    ) as mock_embed:
        first_count = run_backfill(session)
        second_count = run_backfill(session)

    assert first_count >= 1
    assert second_count == 0
    assert mock_embed.call_count == first_count
