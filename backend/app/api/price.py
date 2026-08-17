import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.price import PriceCreate, PriceOut, PriceUpdate
from app.core.database import get_db
from app.models import Material, Price, Supplier

router = APIRouter(prefix="/prices")


def _active_price_query(db: Session, material_id: uuid.UUID, supplier_id: uuid.UUID):
    return db.query(Price).filter(
        Price.material_id == material_id,
        Price.supplier_id == supplier_id,
        Price.valid_to.is_(None),
    )


@router.post("", response_model=PriceOut, status_code=201)
def create_price(payload: PriceCreate, db: Session = Depends(get_db)) -> Price:
    if db.get(Material, payload.material_id) is None:
        raise HTTPException(status_code=404, detail="Material not found")
    if db.get(Supplier, payload.supplier_id) is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if payload.valid_to is None and _active_price_query(
        db, payload.material_id, payload.supplier_id
    ).first():
        raise HTTPException(
            status_code=409,
            detail="An active price already exists for this material/supplier pair",
        )

    price = Price(
        material_id=payload.material_id,
        supplier_id=payload.supplier_id,
        price=payload.price,
        currency=payload.currency,
        availability=payload.availability,
        min_order_qty=payload.min_order_qty,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    db.add(price)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An active price already exists for this material/supplier pair",
        ) from exc
    db.refresh(price)
    return price


@router.get("", response_model=list[PriceOut])
def list_prices(
    material_id: uuid.UUID | None = Query(default=None),
    supplier_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[Price]:
    query = db.query(Price)
    if material_id is not None:
        query = query.filter(Price.material_id == material_id)
    if supplier_id is not None:
        query = query.filter(Price.supplier_id == supplier_id)
    return list(query.order_by(Price.valid_from.desc()).all())


@router.get("/{price_id}", response_model=PriceOut)
def get_price(price_id: uuid.UUID, db: Session = Depends(get_db)) -> Price:
    price = db.get(Price, price_id)
    if price is None:
        raise HTTPException(status_code=404, detail="Price not found")
    return price


@router.put("/{price_id}", response_model=PriceOut)
def update_price(
    price_id: uuid.UUID, payload: PriceUpdate, db: Session = Depends(get_db)
) -> Price:
    """Версионированное обновление: закрывает текущую строку (valid_to = сегодня)
    и создаёт новую с обновлёнными полями — Price неизменяем по докстрингу модели.
    PATCH-семантика: поля, отсутствующие в payload, наследуются от закрываемой
    строки, а не сбрасываются на дефолт/None."""
    existing = db.get(Price, price_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Price not found")

    if payload.valid_to is None:
        conflict = (
            _active_price_query(db, existing.material_id, existing.supplier_id)
            .filter(Price.id != price_id)
            .first()
        )
        if conflict is not None:
            raise HTTPException(
                status_code=409,
                detail="An active price already exists for this material/supplier pair",
            )

    if existing.valid_to is None:
        existing.valid_to = datetime.date.today()

    fields = payload.model_dump(exclude_unset=True, exclude={"valid_from", "valid_to"})
    new_price = Price(
        material_id=existing.material_id,
        supplier_id=existing.supplier_id,
        price=fields.get("price", existing.price),
        currency=fields.get("currency", existing.currency),
        availability=fields.get("availability", existing.availability),
        min_order_qty=fields.get("min_order_qty", existing.min_order_qty),
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        source_import_id=existing.source_import_id,
    )
    db.add(new_price)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An active price already exists for this material/supplier pair",
        ) from exc
    db.refresh(new_price)
    return new_price


@router.delete("/{price_id}", status_code=204)
def delete_price(price_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    """Удалять можно только ошибочно созданные активные записи — закрытые
    (valid_to заполнен) строки хранят историю и не удаляются, см. Price."""
    price = db.get(Price, price_id)
    if price is None:
        raise HTTPException(status_code=404, detail="Price not found")
    if price.valid_to is not None:
        raise HTTPException(
            status_code=409, detail="Cannot delete a closed (historical) price record"
        )
    db.delete(price)
    db.commit()
