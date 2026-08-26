import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.allocation.price_comparison import get_price_comparison
from app.api.schemas.project import (
    LatestAllocationRunOut,
    PriceComparisonOut,
    ProjectCreate,
    ProjectItemCreate,
    ProjectItemOut,
    ProjectItemUpdate,
    ProjectOut,
    ProjectUpdate,
    ProjectWithItemsOut,
)
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models import (
    AllocationLine,
    AllocationRun,
    Material,
    Order,
    OrderItem,
    Project,
    ProjectItem,
    PurchaseRecord,
    User,
)

router = APIRouter(prefix="/projects", dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.query(Project).order_by(Project.created_at.desc()).all())


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    project = Project(title=payload.title, created_by_user_id=current_user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID, payload: ProjectUpdate, db: Session = Depends(get_db)
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project.title = payload.title
    db.commit()
    db.refresh(project)
    return project


@router.post("/{project_id}/complete", response_model=ProjectOut)
def complete_project(project_id: uuid.UUID, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status != "ordered":
        raise HTTPException(
            status_code=409,
            detail="Проект можно завершить только после отправки ордеров поставщикам.",
        )
    project.status = "completed"
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


@router.get("/{project_id}/price-comparison", response_model=PriceComparisonOut)
def get_project_price_comparison(
    project_id: uuid.UUID, db: Session = Depends(get_db)
) -> PriceComparisonOut:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return PriceComparisonOut(rows=get_price_comparison(db, project_id))


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


class ProjectHasSentOrdersError(Exception):
    """At least one Order for this project has status != "draft" — it
    represents a document that actually left the system to a real supplier
    (ADR-0007 п.2 "snapshot, not cache"). Deleting the project must not be
    able to silently erase that history. See ADR-0009 п.1."""

    def __init__(self, project_id: uuid.UUID):
        self.project_id = project_id
        super().__init__(f"Project {project_id} has non-draft orders")


def delete_project(db: Session, project_id: uuid.UUID) -> None:
    """Cascades a Project delete across every table that references it —
    PurchaseRecord, Order/OrderItem, AllocationRun/AllocationLine,
    ProjectItem — in one transaction, refusing entirely if any Order has
    left draft status. See ADR-0009.

    Order/OrderItem and AllocationRun/AllocationLine are deleted
    independently of each other — OrderItem copies its values from
    AllocationLine at Order-creation time rather than holding a foreign key
    to it (ADR-0007 п.2), so neither pair depends on the other's deletion
    order; each pair only has to go child-before-parent internally.
    """
    has_sent_orders = (
        db.query(Order)
        .filter(Order.project_id == project_id, Order.status != "draft")
        .first()
        is not None
    )
    if has_sent_orders:
        raise ProjectHasSentOrdersError(project_id)

    db.query(PurchaseRecord).filter(PurchaseRecord.project_id == project_id).delete(
        synchronize_session=False
    )

    order_ids = [
        o.id for o in db.query(Order.id).filter(Order.project_id == project_id).all()
    ]
    if order_ids:
        db.query(OrderItem).filter(OrderItem.order_id.in_(order_ids)).delete(
            synchronize_session=False
        )
        db.query(Order).filter(Order.id.in_(order_ids)).delete(synchronize_session=False)

    run_ids = [
        r.id
        for r in db.query(AllocationRun.id).filter(AllocationRun.project_id == project_id).all()
    ]
    if run_ids:
        db.query(AllocationLine).filter(AllocationLine.allocation_run_id.in_(run_ids)).delete(
            synchronize_session=False
        )
        db.query(AllocationRun).filter(AllocationRun.id.in_(run_ids)).delete(
            synchronize_session=False
        )

    db.query(ProjectItem).filter(ProjectItem.project_id == project_id).delete(
        synchronize_session=False
    )
    db.query(Project).filter(Project.id == project_id).delete(synchronize_session=False)

    db.commit()


@router.delete("/{project_id}", status_code=204)
def delete_project_endpoint(project_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        delete_project(db, project_id)
    except ProjectHasSentOrdersError as exc:
        raise HTTPException(
            status_code=409,
            detail="У проекта есть отправленные поставщику ордера — удаление недоступно.",
        ) from exc
