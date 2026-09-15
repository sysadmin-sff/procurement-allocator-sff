import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.category import CategoryCreate, CategoryOut, CategoryUpdate
from app.auth.dependencies import require_role
from app.core.database import get_db
from app.models import Category, Material

router = APIRouter(prefix="/categories", dependencies=[Depends(require_role("admin"))])


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[Category]:
    return list(db.query(Category).order_by(Category.name).all())


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)) -> Category:
    category = Category(
        name=payload.name,
        sku_prefix=payload.sku_prefix,
        requires_single_supplier=payload.requires_single_supplier,
    )
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Category with this name or sku_prefix already exists"
        ) from exc
    db.refresh(category)
    return category


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: uuid.UUID, payload: CategoryUpdate, db: Session = Depends(get_db)
) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    fields = payload.model_dump(exclude_unset=True)
    for field_name, value in fields.items():
        setattr(category, field_name, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Category with this name already exists"
        ) from exc
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    material_count = db.query(Material).filter(Material.category_id == category_id).count()
    if material_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Category is referenced by {material_count} material(s), cannot delete",
        )

    db.delete(category)
    db.commit()
