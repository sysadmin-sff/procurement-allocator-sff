import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
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
    order_expected_totals,
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
from app.api.schemas.order_response_parser import (
    ExtraLineOut,
    MatchedLineOut,
    MissingItemOut,
    ParseOrderResponseOut,
)
from app.api.schemas.price import PriceOut
from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models import Order, Price, Project, User
from app.order_response_parser.service import (
    OrderNotFoundError,
    OrderResponseParsingError,
    UnsupportedFileTypeError,
    parse_order_response,
)

router = APIRouter(dependencies=[Depends(get_current_user)])

MAX_ORDER_RESPONSE_FILE_SIZE = 10 * 1024 * 1024
"""10MB — see ADR-0018 task description. The file is only ever held in
memory for the duration of the OpenAI call (ADR-0018 §7), never written to
disk, so this bound also caps peak request memory."""


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
        **order_expected_totals(order),
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
    current_user: User = Depends(get_current_user),
) -> list[OrderOut] | JSONResponse:
    try:
        orders = create_orders_for_run(
            db,
            project_id,
            run_id,
            replace_drafts=payload.replace_drafts,
            acknowledge_conflict=payload.acknowledge_conflict,
            created_by_user_id=current_user.id,
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


@router.get("/materials/{material_id}/prices", response_model=list[PriceOut])
def get_material_prices(material_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Price]:
    """Active prices (valid_to IS NULL) for one material across all
    suppliers — candidate source for the ADR-0014 find-replacement flow.
    Thin endpoint, no new business logic (ADR-0014 п.1). Lives here, not in
    material.py, because material.py is admin-only reference-data CRUD
    (ADR-0024 §4) while this read backs an operational, any-role flow —
    see ADR-0024 §4 permission-matrix follow-up."""
    return list(
        db.query(Price)
        .filter(Price.material_id == material_id, Price.valid_to.is_(None))
        .all()
    )


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
    current_user: User = Depends(get_current_user),
) -> OrderItemOut | JSONResponse:
    if db.get(Order, order_id) is None:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        item = replace_and_sync_order(
            db, order_id, item_id, payload.supplier_id, overridden_by_user_id=current_user.id
        )
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


@router.post(
    "/orders/{order_id}/parse-response",
    response_model=ParseOrderResponseOut,
)
async def parse_order_response_endpoint(
    order_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> ParseOrderResponseOut:
    """Multipart upload of a supplier's response document (PDF/image) — see
    ADR-0018. Read-only preview: never writes to OrderItem/PurchaseRecord:
    the frontend applies the result via the existing PATCH .../items/{id}
    (ADR-0007/ADR-0013) and POST .../purchase-records (ADR-0008) endpoints.
    The file is held in memory only for this request, never persisted
    (ADR-0018 §7)."""
    file_bytes = await file.read()
    if len(file_bytes) > MAX_ORDER_RESPONSE_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Файл слишком большой (максимум 10MB).")

    try:
        matched, missing, extra = parse_order_response(
            db,
            order_id,
            file_bytes=file_bytes,
            content_type=file.content_type or "",
        )
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Order not found") from exc
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=422,
            detail="Неподдерживаемый тип файла — загрузите PDF или изображение (PNG/JPEG/WEBP).",
        ) from exc
    except OrderResponseParsingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ParseOrderResponseOut(
        matched=[
            MatchedLineOut(
                order_item_id=line.matched_order_item_id,
                raw_description=line.raw_description,
                price=line.price,
                quantity=line.quantity,
                confidence=line.confidence,
                reasoning=line.reasoning,
            )
            for line in matched
        ],
        missing=[
            MissingItemOut(
                order_item_id=item.id,
                material_id=item.material_id,
                canonical_name=item.material.canonical_name,
                quantity=item.quantity,
                quoted_price=float(item.quoted_price),
            )
            for item in missing
        ],
        extra=[
            ExtraLineOut(
                raw_description=line.raw_description,
                price=line.price,
                quantity=line.quantity,
                confidence=line.confidence,
                reasoning=line.reasoning,
            )
            for line in extra
        ],
    )
