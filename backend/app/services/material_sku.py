"""Atomic internal_sku generation for Material — see ADR-0034 п.4/п.7.

Single implementation, used by both material-creation paths in the system
(app/api/material.py::create_material and
app/price_ingestion/apply.py::_apply_new) so the atomic-counter formula
never has two copies to keep in sync — same one-function convention as
calculate_tax/resolve_material_name/version_price elsewhere in this project.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Category


def generate_next_sku(db: Session, category_id: uuid.UUID) -> str:
    """Atomic counter increment — see ADR-0034 п.4. UPDATE ... RETURNING is a
    single statement that both reads the current value and takes Postgres's
    row-level lock on this Category row, so two concurrent creates against
    the same category can never read the same next_sku_number: the second
    transaction blocks until the first commits or rolls back. Must run in
    the same transaction as the Material INSERT that follows (no commit
    between this call and the caller's own db.add(material); db.commit()).

    Raises HTTPException(404) if category_id doesn't exist -- same error
    shape for both callers, not two different messages for one condition.
    """
    result = db.execute(
        update(Category)
        .where(Category.id == category_id)
        .values(next_sku_number=Category.next_sku_number + 1)
        .returning(Category.next_sku_number, Category.sku_prefix)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Category not found")
    new_number, prefix = row
    return f"{prefix}-{new_number - 1:03d}"
