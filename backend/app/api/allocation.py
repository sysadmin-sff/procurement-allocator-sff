import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.allocation.service import (
    EmptyProjectError,
    InvalidOverrideSupplierError,
    LineNotFoundError,
    override_allocation_line_supplier,
    run_allocation,
)
from app.api.schemas.allocation import AllocationLineOut, AllocationLineOverrideIn, AllocationRunOut
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models import AllocationRun, Project, User

router = APIRouter(prefix="/projects/{project_id}", dependencies=[Depends(get_current_user)])


@router.post("/allocate", response_model=AllocationRunOut)
def allocate(project_id: uuid.UUID, db: Session = Depends(get_db)) -> AllocationRun:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        return run_allocation(db, project_id)
    except EmptyProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/allocations/{run_id}", response_model=AllocationRunOut)
def get_allocation_run(
    project_id: uuid.UUID, run_id: uuid.UUID, db: Session = Depends(get_db)
) -> AllocationRun:
    run = db.get(AllocationRun, run_id)
    if run is None or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Allocation run not found")
    return run


@router.patch("/allocations/{run_id}/lines/{line_id}", response_model=AllocationLineOut)
def override_allocation_line(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: AllocationLineOverrideIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = db.get(AllocationRun, run_id)
    if run is None or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Allocation run not found")

    try:
        return override_allocation_line_supplier(
            db,
            run_id,
            line_id,
            payload.supplier_id,
            payload.source_order_item_id,
            overridden_by_user_id=current_user.id,
        )
    except LineNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Allocation line not found") from exc
    except InvalidOverrideSupplierError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
