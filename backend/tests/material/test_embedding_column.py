"""pgvector extension + Material.embedding column — see ADR-0019 §1."""

import pytest
from sqlalchemy import text

from app.core.database import engine


def test_vector_extension_is_installed():
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).first()
    assert result is not None


def test_material_embedding_column_exists_and_is_nullable(db_session, make_material):
    material = make_material()
    assert material.embedding is None


def test_material_embedding_column_stores_a_vector(db_session, make_material):
    session, _material_ids = db_session
    material = make_material()
    material.embedding = [0.1] * 1536
    session.commit()
    session.refresh(material)
    assert len(material.embedding) == 1536
    assert material.embedding[0] == pytest.approx(0.1)
