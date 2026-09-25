import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.schemas.template import (
    ProjectTemplateCreate,
    ProjectTemplateItemCreate,
    ProjectTemplateItemOut,
    ProjectTemplateOut,
    ProjectTemplateUpdate,
)
from app.auth.dependencies import require_role
from app.core.database import get_db
from app.models import Material, ProjectTemplate, ProjectTemplateItem

router = APIRouter(
    prefix="/project-templates", dependencies=[Depends(require_role("admin"))]
)


def _to_out(template: ProjectTemplate) -> ProjectTemplateOut:
    return ProjectTemplateOut(
        id=template.id,
        name=template.name,
        created_at=template.created_at,
        items=[
            ProjectTemplateItemOut(
                id=item.id,
                material_id=item.material_id,
                canonical_name=item.material.canonical_name,
                unit=item.material.unit,
                category_name=item.material.category.name,
            )
            for item in template.items
        ],
    )


def _get_template_or_404(template_id: uuid.UUID, db: Session) -> ProjectTemplate:
    template = (
        db.query(ProjectTemplate)
        .options(joinedload(ProjectTemplate.items).joinedload(ProjectTemplateItem.material))
        .filter(ProjectTemplate.id == template_id)
        .first()
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Project template not found")
    return template


@router.get("", response_model=list[ProjectTemplateOut])
def list_templates(db: Session = Depends(get_db)) -> list[ProjectTemplateOut]:
    templates = (
        db.query(ProjectTemplate)
        .options(joinedload(ProjectTemplate.items).joinedload(ProjectTemplateItem.material))
        .order_by(ProjectTemplate.name)
        .all()
    )
    return [_to_out(t) for t in templates]


@router.post("", response_model=ProjectTemplateOut, status_code=201)
def create_template(
    payload: ProjectTemplateCreate, db: Session = Depends(get_db)
) -> ProjectTemplateOut:
    template = ProjectTemplate(name=payload.name)
    db.add(template)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Project template with this name already exists"
        ) from exc
    db.refresh(template)
    return _to_out(template)


@router.patch("/{template_id}", response_model=ProjectTemplateOut)
def rename_template(
    template_id: uuid.UUID, payload: ProjectTemplateUpdate, db: Session = Depends(get_db)
) -> ProjectTemplateOut:
    template = _get_template_or_404(template_id, db)
    template.name = payload.name
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Project template with this name already exists"
        ) from exc
    db.refresh(template)
    return _to_out(template)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    template = _get_template_or_404(template_id, db)
    db.delete(template)
    db.commit()


@router.post("/{template_id}/items", response_model=ProjectTemplateOut, status_code=201)
def add_template_item(
    template_id: uuid.UUID, payload: ProjectTemplateItemCreate, db: Session = Depends(get_db)
) -> ProjectTemplateOut:
    template = _get_template_or_404(template_id, db)
    if db.get(Material, payload.material_id) is None:
        raise HTTPException(status_code=404, detail="Material not found")

    item = ProjectTemplateItem(template_id=template_id, material_id=payload.material_id)
    db.add(item)
    db.commit()

    template = _get_template_or_404(template_id, db)
    return _to_out(template)


@router.delete("/{template_id}/items/{item_id}", response_model=ProjectTemplateOut)
def remove_template_item(
    template_id: uuid.UUID, item_id: uuid.UUID, db: Session = Depends(get_db)
) -> ProjectTemplateOut:
    template = _get_template_or_404(template_id, db)
    item = db.get(ProjectTemplateItem, item_id)
    if item is None or item.template_id != template_id:
        raise HTTPException(status_code=404, detail="Template item not found")

    db.delete(item)
    db.commit()

    template = _get_template_or_404(template_id, db)
    return _to_out(template)
