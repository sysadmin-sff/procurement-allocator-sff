import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.material import MaterialCreate, MaterialOut, MaterialUpdate
from app.api.schemas.price import PriceOut
from app.core.database import get_db
from app.models import Material, Price

router = APIRouter(prefix="/materials")


@router.get("/search", response_model=list[MaterialOut])
def search_materials(
    q: str = Query(..., min_length=2), db: Session = Depends(get_db)
) -> list[Material]:
    return list(
        db.query(Material)
        .filter(Material.canonical_name.ilike(f"%{q}%"))
        .order_by(Material.canonical_name)
        .limit(20)
        .all()
    )


@router.post("", response_model=MaterialOut, status_code=201)
def create_material(payload: MaterialCreate, db: Session = Depends(get_db)) -> Material:
    material = Material(
        internal_sku=payload.internal_sku,
        canonical_name=payload.canonical_name,
        category=payload.category,
        unit=payload.unit,
        attributes=payload.attributes,
    )
    db.add(material)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Material with this internal_sku already exists"
        ) from exc
    db.refresh(material)
    return material


@router.get("", response_model=list[MaterialOut])
def list_materials(db: Session = Depends(get_db)) -> list[Material]:
    return list(db.query(Material).order_by(Material.canonical_name).all())


@router.get("/{material_id}", response_model=MaterialOut)
def get_material(material_id: uuid.UUID, db: Session = Depends(get_db)) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found")
    return material


@router.get("/{material_id}/prices", response_model=list[PriceOut])
def get_material_prices(material_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Price]:
    """Active prices (valid_to IS NULL) for one material across all
    suppliers — candidate source for the ADR-0014 find-replacement flow.
    Thin endpoint, no new business logic (ADR-0014 п.1)."""
    return list(
        db.query(Price)
        .filter(Price.material_id == material_id, Price.valid_to.is_(None))
        .all()
    )


@router.put("/{material_id}", response_model=MaterialOut)
def update_material(
    material_id: uuid.UUID, payload: MaterialUpdate, db: Session = Depends(get_db)
) -> Material:
    """PATCH-семантика: поля, отсутствующие в payload, не трогаются."""
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found")

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(material, field_name, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Material with this internal_sku already exists"
        ) from exc
    db.refresh(material)
    return material


@router.delete("/{material_id}", status_code=204)
def delete_material(material_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found")
    db.delete(material)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Material is referenced by other records"
        ) from exc
