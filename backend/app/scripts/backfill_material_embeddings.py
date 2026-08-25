"""Одноразовый бэкафилл эмбеддингов для Material с embedding IS NULL —
см. ADR-0019 §1. Того же семейства, что import_real_data.py/seed.py:
операторский скрипт, не API endpoint.

Идемпотентен: повторный запуск трогает только строки, у которых
embedding всё ещё NULL (например, из-за сбоя API при предыдущем запуске
или при create_material, ADR-0019 §1).

Использование:
    python -m app.scripts.backfill_material_embeddings
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Material
from app.price_ingestion.embeddings import EmbeddingError, embed_text, material_embedding_input


def run_backfill(db: Session) -> int:
    """Embeds every Material with embedding IS NULL. Returns the count of
    materials successfully embedded. A per-row EmbeddingError is logged and
    skipped (not raised) so one bad row doesn't abort the whole batch —
    left for the next run, same as any other embedding=NULL case."""
    materials = db.scalars(select(Material).where(Material.embedding.is_(None))).all()

    embedded_count = 0
    for material in materials:
        try:
            material.embedding = embed_text(
                material_embedding_input(material.canonical_name, material.attributes)
            )
        except EmbeddingError as exc:
            print(f"Skipping material {material.id} ({material.canonical_name!r}): {exc}")
            continue
        embedded_count += 1

    db.commit()
    return embedded_count


if __name__ == "__main__":
    session = SessionLocal()
    try:
        count = run_backfill(session)
        print(f"Embedded {count} material(s).")
    finally:
        session.close()
