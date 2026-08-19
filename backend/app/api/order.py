import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.allocation.order_service import (
    DraftOrderConflictError,
    OrderItemNotFoundError,
    RunNotFoundError,
    create_orders_for_run,
    price_delta,
    set_confirmed_price,
)
from app.api.schemas.order import (
    CreateOrdersIn,
    OrderDraftConflictOut,
    OrderItemConfirmIn,
    OrderItemOut,
    OrderOut,
)
from app.core.database import get_db
from app.models import Order, Project

router = APIRouter()


def _to_order_item_out(item) -> OrderItemOut:
    delta, delta_pct = price_delta(item.quoted_price, item.confirmed_price)
    return OrderItemOut(
        id=item.id,
        order_id=item.order_id,
        material_id=item.material_id,
        quantity=item.quantity,
        quoted_price=item.quoted_price,
        confirmed_price=item.confirmed_price,
        confirmed_at=item.confirmed_at,
        price_delta=delta,
        price_delta_pct=delta_pct,
    )


def _to_order_out(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        project_id=order.project_id,
        supplier_id=order.supplier_id,
        status=order.status,
        total_amount=order.total_amount,
        delivery_fee=order.delivery_fee,
        items=[_to_order_item_out(item) for item in order.items],
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
    return [_to_order_out(order) for order in orders]


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
    return [_to_order_out(order) for order in orders]


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: uuid.UUID, db: Session = Depends(get_db)) -> OrderOut:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return _to_order_out(order)


@router.patch("/orders/{order_id}/items/{item_id}", response_model=OrderItemOut)
def patch_order_item_confirmed_price(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: OrderItemConfirmIn,
    db: Session = Depends(get_db),
) -> OrderItemOut:
    if db.get(Order, order_id) is None:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        item = set_confirmed_price(db, order_id, item_id, payload.confirmed_price)
    except OrderItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Order item not found") from exc
    return _to_order_item_out(item)
