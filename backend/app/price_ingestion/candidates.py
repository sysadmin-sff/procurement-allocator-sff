"""Alias short-circuit (ADR-0019 §2, still used by matching.py) and
pgvector top-K candidate search (ADR-0019 §3). find_top_candidates/TOP_K/
DUPLICATE_DISTANCE_THRESHOLD are no longer used by matching.py — ADR-0025
§1 removed vector prefiltering from the matching path (fixed, small
catalog passed whole instead) — but are left in place here, not deleted:
ADR-0025 §6 explicitly keeps Material's vector infrastructure untouched,
and this module belongs to it, not to the matching path specifically.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Material, SupplierMaterialAlias

TOP_K = 5
DUPLICATE_DISTANCE_THRESHOLD = 0.15
"""Cosine distance below which two embeddings are considered the same
underlying material — used both to cut off top-K candidates worth showing
the LLM and to flag possible duplicate new-lines (ADR-0019 §4). Not
validated against real data yet — see docs/known-issues.md."""


def find_known_alias(
    db: Session, supplier_id: uuid.UUID, raw_name: str
) -> SupplierMaterialAlias | None:
    """Exact-match short-circuit before any embedding/LLM call — see
    ADR-0019 §2. Scoped to (supplier_id, supplier_raw_name)."""
    return db.scalar(
        select(SupplierMaterialAlias).where(
            SupplierMaterialAlias.supplier_id == supplier_id,
            SupplierMaterialAlias.supplier_raw_name == raw_name,
        )
    )


def find_top_candidates(
    db: Session, embedding: list[float], k: int = TOP_K
) -> list[Material]:
    """Top-k Material by cosine distance to `embedding`, excluding rows
    with embedding IS NULL (they simply can't be searched — ADR-0019 §1,
    "деградация полноты поиска, не ошибка")."""
    return list(
        db.scalars(
            select(Material)
            .where(Material.embedding.is_not(None))
            .order_by(Material.embedding.cosine_distance(embedding))
            .limit(k)
        ).all()
    )
