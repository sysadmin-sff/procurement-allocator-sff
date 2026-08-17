import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.project import (
    LatestAllocationRunOut,
    ProjectCreate,
    ProjectItemCreate,
    ProjectItemOut,
    ProjectItemUpdate,
    ProjectOut,
    ProjectWithItemsOut,
)
from app.core.database import get_db
from app.models import AllocationRun, Material, Project, ProjectItem

router = APIRouter(prefix="/projects")


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.query(Project).order_by(Project.created_at.desc()).all())


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    project = Project(title=payload.title, created_by=payload.created_by)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectWithItemsOut)
def get_project(project_id: uuid.UUID, db: Session = Depends(get_db)) -> ProjectWithItemsOut:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    latest_run = (
        db.query(AllocationRun)
        .filter(AllocationRun.project_id == project_id)
        .order_by(AllocationRun.created_at.desc())
        .first()
    )

    return ProjectWithItemsOut(
        id=project.id,
        title=project.title,
        created_by=project.created_by,
        status=project.status,
        created_at=project.created_at,
        items=[ProjectItemOut.model_validate(item) for item in project.items],
        latest_allocation_run=(
            LatestAllocationRunOut.model_validate(latest_run) if latest_run else None
        ),
    )


@router.post("/{project_id}/items", response_model=ProjectItemOut, status_code=201)
def add_project_item(
    project_id: uuid.UUID, payload: ProjectItemCreate, db: Session = Depends(get_db)
) -> ProjectItem:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if db.get(Material, payload.material_id) is None:
        raise HTTPException(status_code=404, detail="Material not found")

    item = ProjectItem(
        project_id=project_id, material_id=payload.material_id, quantity=payload.quantity
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _get_project_item_or_404(
    project_id: uuid.UUID, item_id: uuid.UUID, db: Session
) -> ProjectItem:
    item = db.get(ProjectItem, item_id)
    if item is None or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="Project item not found")
    return item


@router.patch("/{project_id}/items/{item_id}", response_model=ProjectItemOut)
def update_project_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ProjectItemUpdate,
    db: Session = Depends(get_db),
) -> ProjectItem:
    item = _get_project_item_or_404(project_id, item_id, db)
    item.quantity = payload.quantity
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{project_id}/items/{item_id}", status_code=204)
def delete_project_item(
    project_id: uuid.UUID, item_id: uuid.UUID, db: Session = Depends(get_db)
) -> None:
    item = _get_project_item_or_404(project_id, item_id, db)
    db.delete(item)
    db.commit()
