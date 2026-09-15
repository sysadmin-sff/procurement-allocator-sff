import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.material import MaterialCreate, MaterialOut, MaterialUpdate
from app.auth.dependencies import require_role
from app.core.database import get_db
from app.models import Material
from app.price_ingestion.embeddings import EmbeddingError, embed_text, material_embedding_input
from app.services.material_sku import generate_next_sku

router = APIRouter(prefix="/materials", dependencies=[Depends(require_role("admin"))])


def _escape_ilike(value: str) -> str:
    """Escapes ILIKE wildcard characters (%, _) and the escape character
    itself (\\) in user-supplied search text, so a query containing a
    literal '%' or '_' is matched as that literal character rather than as
    a wildcard — see docs/known-issues.md."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/search", response_model=list[MaterialOut])
def search_materials(
    q: str = Query(..., min_length=2), db: Session = Depends(get_db)
) -> list[Material]:
    return list(
        db.query(Material)
        .filter(Material.canonical_name.ilike(f"%{_escape_ilike(q)}%", escape="\\"))
        .order_by(Material.canonical_name)
        .limit(20)
        .all()
    )


@router.post("", response_model=MaterialOut, status_code=201)
def create_material(payload: MaterialCreate, db: Session = Depends(get_db)) -> Material:
    internal_sku = generate_next_sku(db, payload.category_id)

    material = Material(
        internal_sku=internal_sku,
        canonical_name=payload.canonical_name,
        category_id=payload.category_id,
        unit=payload.unit,
        attributes=payload.attributes,
    )
    try:
        material.embedding = embed_text(
            material_embedding_input(payload.canonical_name, payload.attributes)
        )
    except EmbeddingError:
        # Graceful degradation — see ADR-0019 §1: a manual CRUD create must
        # not become dependent on a third-party API's availability.
        # embedding stays NULL, picked up later by the backfill script.
        material.embedding = None

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


@router.put("/{material_id}", response_model=MaterialOut)
def update_material(
    material_id: uuid.UUID, payload: MaterialUpdate, db: Session = Depends(get_db)
) -> Material:
    """PATCH-семантика: поля, отсутствующие в payload, не трогаются.
    category_id может меняться (переклассификация) без пересчёта internal_sku
    — см. ADR-0034 п.4."""
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found")

    fields = payload.model_dump(exclude_unset=True)
    text_changed = "canonical_name" in fields or "attributes" in fields

    for field_name, value in fields.items():
        setattr(material, field_name, value)

    if text_changed:
        try:
            material.embedding = embed_text(
                material_embedding_input(material.canonical_name, material.attributes)
            )
        except EmbeddingError:
            # Graceful degradation — see ADR-0019 §1: keep the previous
            # embedding rather than clearing it; it's stale but still more
            # relevant than NULL for vector search.
            pass

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
