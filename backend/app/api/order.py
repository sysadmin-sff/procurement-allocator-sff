import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.allocation.order_service import (
    DraftOrderConflictError,
    DuplicateMaterialInDraftError,
    MaterialNotInLatestRunError,
    MultipleDraftOrdersConflictError,
    OrderItemNotFoundError,
    RunNotFoundError,
    create_orders_for_run,
    find_replacement_candidates,
    price_delta,
    replace_and_sync_order,
    replacement_info_for_item,
    set_order_item_fields,
)
from app.allocation.service import InvalidOverrideSupplierError
from app.api.schemas.order import (
    CreateOrdersIn,
    FindReplacementOut,
    OrderDraftConflictOut,
    OrderItemConfirmIn,
    OrderItemOut,
    OrderOut,
    ReplaceAndOrderIn,
)
from app.core.database import get_db
from app.models import Order, Project

router = APIRouter()


def _to_order_item_out(db: Session, item) -> OrderItemOut:
    delta, delta_pct = price_delta(item.quoted_price, item.confirmed_price)
    replaced_supplier_id, replaced_supplier_name, replacement_draft_order_id = (
        replacement_info_for_item(db, item)
    )
    return OrderItemOut(
        id=item.id,
        order_id=item.order_id,
        material_id=item.material_id,
        quantity=item.quantity,
        quoted_price=item.quoted_price,
        received_price=item.received_price,
        confirmed_price=item.confirmed_price,
        confirmed_at=item.confirmed_at,
        declined_at=item.declined_at,
        decline_reason=item.decline_reason,
        price_delta=delta,
        price_delta_pct=delta_pct,
        replaced_by_supplier_id=replaced_supplier_id,
        replaced_by_supplier_name=replaced_supplier_name,
        replacement_draft_order_id=replacement_draft_order_id,
    )


def _to_order_out(db: Session, order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        project_id=order.project_id,
        supplier_id=order.supplier_id,
        status=order.status,
        total_amount=order.total_amount,
        delivery_fee=order.delivery_fee,
        items=[_to_order_item_out(db, item) for item in order.items],
    )


@router.post(
    "/projects/{project_id}/allocations/{run_id}/orders",
    response_model=list[OrderOut],
    status_code=201,
)
def create_orders(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: CreateOrdersIn = CreateOrdersIn(),
    db: Session = Depends(get_db),
) -> list[OrderOut] | JSONResponse:
    try:
        orders = create_orders_for_run(
            db, project_id, run_id, replace_drafts=payload.replace_drafts
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Allocation run not found") from exc
    except DraftOrderConflictError as exc:
        body = OrderDraftConflictOut(
            suppliers_with_existing_drafts=exc.suppliers_with_existing_drafts
        )
        return JSONResponse(status_code=409, content=body.model_dump(mode="json"))
    return [_to_order_out(db, order) for order in orders]


@router.get("/projects/{project_id}/orders", response_model=list[OrderOut])
def list_project_orders(project_id: uuid.UUID, db: Session = Depends(get_db)) -> list[OrderOut]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    orders = (
        db.query(Order)
        .filter(Order.project_id == project_id)
        .order_by(Order.id)
        .all()
    )
    return [_to_order_out(db, order) for order in orders]


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: uuid.UUID, db: Session = Depends(get_db)) -> OrderOut:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return _to_order_out(db, order)


@router.patch("/orders/{order_id}/items/{item_id}", response_model=OrderItemOut)
def patch_order_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: OrderItemConfirmIn,
    db: Session = Depends(get_db),
) -> OrderItemOut:
    if db.get(Order, order_id) is None:
        raise HTTPException(status_code=404, detail="Order not found")

    fields_set = payload.model_fields_set
    kwargs = {
        field: getattr(payload, field)
        for field in ("confirmed_price", "received_price", "declined", "decline_reason")
        if field in fields_set
    }

    try:
        item = set_order_item_fields(db, order_id, item_id, **kwargs)
    except OrderItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Order item not found") from exc
    return _to_order_item_out(db, item)


@router.post(
    "/orders/{order_id}/items/{item_id}/find-replacement",
    response_model=FindReplacementOut,
)
def find_replacement(
    order_id: uuid.UUID, item_id: uuid.UUID, db: Session = Depends(get_db)
) -> FindReplacementOut:
    if db.get(Order, order_id) is None:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        line_id, candidates = find_replacement_candidates(db, order_id, item_id)
    except OrderItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Order item not found") from exc
    except MaterialNotInLatestRunError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FindReplacementOut(line_id=line_id, candidates=candidates)


@router.post(
    "/orders/{order_id}/items/{item_id}/replace-and-order",
    response_model=OrderItemOut,
)
def replace_and_order(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ReplaceAndOrderIn,
    db: Session = Depends(get_db),
) -> OrderItemOut | JSONResponse:
    if db.get(Order, order_id) is None:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        item = replace_and_sync_order(db, order_id, item_id, payload.supplier_id)
    except OrderItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Order item not found") from exc
    except MaterialNotInLatestRunError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidOverrideSupplierError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MultipleDraftOrdersConflictError as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    except DuplicateMaterialInDraftError as exc:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    return _to_order_item_out(db, item)
