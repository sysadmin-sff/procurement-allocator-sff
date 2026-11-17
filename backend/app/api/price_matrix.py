"""Матрица цен и история пары (ADR-0054) — только admin (ADR-0055).

Отдельный роутер, а не часть price.py: CRUD /prices открыт любой роли,
а сводный контроль цен остаётся у руководства. Подключается в main.py ДО
price.py, иначе "/prices/matrix" попадает в "/prices/{price_id}" и даёт 422.
"""

import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas.price import PriceDynamicsOut, PriceHistoryEntryOut, PriceMatrixOut
from app.auth.dependencies import require_role
from app.core.database import get_db
from app.services.price_matrix import (
    PriceDynamics,
    PriceHistoryEntry,
    PriceMatrix,
    build_price_matrix,
    default_dynamics_range,
    price_dynamics,
    price_history,
)

router = APIRouter(prefix="/prices", dependencies=[Depends(require_role("admin"))])


@router.get("/matrix", response_model=PriceMatrixOut)
def get_price_matrix(
    compare_to: datetime.date | None = Query(default=None),
    period_end: datetime.date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PriceMatrix:
    """Без compare_to — сравнение с предыдущей версией каждой пары,
    с compare_to — с ценой, действовавшей на эту дату. С period_end — режим
    «за период» (ADR-0056): в ячейке цена на period_end, а не текущая."""
    if period_end is not None and (compare_to is None or compare_to > period_end):
        raise HTTPException(
            status_code=422,
            detail="period_end requires compare_to, and compare_to must not be after it",
        )
    return build_price_matrix(db, compare_to=compare_to, period_end=period_end)


@router.get("/history", response_model=list[PriceHistoryEntryOut])
def get_price_history(
    material_id: uuid.UUID = Query(),
    supplier_id: uuid.UUID = Query(),
    db: Session = Depends(get_db),
) -> list[PriceHistoryEntry]:
    """История пары материал + поставщик с источником каждой версии
    (ADR-0054 §6), новые первыми."""
    return price_history(db, material_id=material_id, supplier_id=supplier_id)


def _parse_month(value: str | None) -> datetime.date | None:
    if value is None:
        return None
    try:
        year, month = (int(part) for part in value.split("-"))
        return datetime.date(year, month, 1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM") from exc


@router.get("/dynamics", response_model=PriceDynamicsOut)
def get_price_dynamics(
    start: str | None = Query(default=None, description="YYYY-MM"),
    end: str | None = Query(default=None, description="YYYY-MM"),
    db: Session = Depends(get_db),
) -> PriceDynamics:
    """Среднее изменение цен по поставщикам и месяцам (ADR-0057). По
    умолчанию — последние 12 месяцев, включая текущий."""
    today = datetime.date.today()
    default_start, default_end = default_dynamics_range(today)
    start_month = _parse_month(start) or default_start
    end_month = _parse_month(end) or default_end
    try:
        return price_dynamics(db, start_month=start_month, end_month=end_month, today=today)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
