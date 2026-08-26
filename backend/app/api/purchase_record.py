import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.purchase_record import (
    PurchaseRecordCreate,
    PurchaseRecordListOut,
    PurchaseRecordOut,
    PurchaseRecordUpdate,
    SupplierTotalOut,
    TotalComparisonOut,
)
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models import Project, PurchaseRecord, User
from app.purchase_records.service import (
    PurchaseRecordNotFoundError,
    create_purchase_record,
    delete_purchase_record,
    get_project_totals,
    get_supplier_totals,
    update_purchase_record,
)

router = APIRouter(
    prefix="/projects/{project_id}/purchase-records", dependencies=[Depends(get_current_user)]
)


def _to_total_comparison_out(comparison) -> TotalComparisonOut:
    return TotalComparisonOut(
        purchased_total=comparison.purchased_total,
        planned_total=comparison.planned_total,
        delta=comparison.delta,
        delta_pct=comparison.delta_pct,
    )


@router.post("", response_model=PurchaseRecordOut, status_code=201)
def create_record(
    project_id: uuid.UUID,
    payload: PurchaseRecordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PurchaseRecord:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return create_purchase_record(
        db,
        project_id=project_id,
        supplier_id=payload.supplier_id,
        raw_description=payload.raw_description,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        material_id=payload.material_id,
        created_by_user_id=current_user.id,
    )


@router.get("", response_model=PurchaseRecordListOut)
def list_records(project_id: uuid.UUID, db: Session = Depends(get_db)) -> PurchaseRecordListOut:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    records = (
        db.query(PurchaseRecord)
        .filter(PurchaseRecord.project_id == project_id)
        .order_by(PurchaseRecord.created_at)
        .all()
    )
    project_total = get_project_totals(db, project_id)
    supplier_totals = get_supplier_totals(db, project_id)

    return PurchaseRecordListOut(
        records=[PurchaseRecordOut.model_validate(r) for r in records],
        project_total=_to_total_comparison_out(project_total),
        supplier_totals=[
            SupplierTotalOut(
                supplier_id=supplier_id,
                purchased_total=comparison.purchased_total,
                planned_total=comparison.planned_total,
                delta=comparison.delta,
                delta_pct=comparison.delta_pct,
            )
            for supplier_id, comparison in supplier_totals.items()
        ],
    )


@router.patch("/{record_id}", response_model=PurchaseRecordOut)
def update_record(
    project_id: uuid.UUID,
    record_id: uuid.UUID,
    payload: PurchaseRecordUpdate,
    db: Session = Depends(get_db),
) -> PurchaseRecord:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        return update_purchase_record(
            db,
            project_id=project_id,
            record_id=record_id,
            supplier_id=payload.supplier_id,
            raw_description=payload.raw_description,
            quantity=payload.quantity,
            unit_price=payload.unit_price,
            material_id=payload.material_id,
        )
    except PurchaseRecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Purchase record not found") from exc


@router.delete("/{record_id}", status_code=204)
def delete_record(
    project_id: uuid.UUID, record_id: uuid.UUID, db: Session = Depends(get_db)
) -> None:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        delete_purchase_record(db, project_id=project_id, record_id=record_id)
    except PurchaseRecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Purchase record not found") from exc
