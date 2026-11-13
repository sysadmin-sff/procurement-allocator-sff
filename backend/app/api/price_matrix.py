"""Матрица цен и история пары (ADR-0054) — только admin (ADR-0055).

Отдельный роутер, а не часть price.py: CRUD /prices открыт любой роли,
а сводный контроль цен остаётся у руководства. Подключается в main.py ДО
price.py, иначе "/prices/matrix" попадает в "/prices/{price_id}" и даёт 422.
"""

import datetime
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas.price import PriceHistoryEntryOut, PriceMatrixOut
from app.auth.dependencies import require_role
from app.core.database import get_db
from app.services.price_matrix import (
    PriceHistoryEntry,
    PriceMatrix,
    build_price_matrix,
    price_history,
)

router = APIRouter(prefix="/prices", dependencies=[Depends(require_role("admin"))])


@router.get("/matrix", response_model=PriceMatrixOut)
def get_price_matrix(
    compare_to: datetime.date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PriceMatrix:
    """Без compare_to — сравнение с предыдущей версией каждой пары,
    с compare_to — с ценой, действовавшей на эту дату."""
    return build_price_matrix(db, compare_to=compare_to)


@router.get("/history", response_model=list[PriceHistoryEntryOut])
def get_price_history(
    material_id: uuid.UUID = Query(),
    supplier_id: uuid.UUID = Query(),
    db: Session = Depends(get_db),
) -> list[PriceHistoryEntry]:
    """История пары материал + поставщик с источником каждой версии
    (ADR-0054 §6), новые первыми."""
    return price_history(db, material_id=material_id, supplier_id=supplier_id)
