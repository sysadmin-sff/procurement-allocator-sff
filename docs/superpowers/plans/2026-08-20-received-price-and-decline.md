# Received Price & Supplier Decline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `OrderItem.received_price` (supplier's first-response price, before negotiation) and an explicit decline signal (`declined_at`/`decline_reason`) to the Order reconciliation flow, per ADR-0013.

**Architecture:** Extend the existing `OrderItem` model with three nullable columns, extend the existing single-item PATCH endpoint (`PATCH /orders/{order_id}/items/{item_id}`) to accept the new fields independently (same semantics `confirmed_price` already uses — explicit `null` clears, field omitted leaves untouched), extend `OrderItemOut`/`OrderItem` (frontend type) to expose them, and extend `OrderDetailPage.tsx`'s existing table with one new price column and one new decline control. No changes to `price_delta` (quoted vs confirmed), no changes to `Order.total_amount`, no new derived/persisted fields beyond a client-side decline counter mirroring the existing discrepancy counter.

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic (backend), React/TypeScript (frontend), pytest, vitest.

**Spec:** [docs/decisions/0013-order-item-received-price-and-decline.md](../../decisions/0013-order-item-received-price-and-decline.md)

## Global Constraints

- Money/quantity logic stays backend-only (CLAUDE.md принцип 4) — `price_delta` computation is not touched; any new client-side comparison (e.g. `received - confirmed`, if ever added) is out of scope here per ADR-0013 §4.
- Material identity/naming rules (CLAUDE.md принципы 2–3) are not implicated by this plan — no new material-matching logic.
- Nullable timestamp-as-flag pattern (`confirmed_at`, `overridden_at`, `ordered_at`) must be followed exactly for `declined_at` — backend stamps `now()`, client never sends a timestamp value.
- `received_price` has no companion timestamp (ADR-0013 §3, "Отклонено: `received_at`") — do not add one.
- `declined_at` must not be mutually exclusive with `received_price`/`confirmed_price` — no validation blocking any combination (ADR-0013 §2).
- Current alembic head at plan-authoring time: `b15597e509ec`. Verify this is still the head before creating the new migration (someone else's migration may have landed since).

---

## File Structure

- Modify `backend/app/models/order.py` — add `received_price`, `declined_at`, `decline_reason` columns to `OrderItem`.
- Create `backend/alembic/versions/<hash>_add_received_price_and_decline_to_order_items.py` — migration for the three new columns.
- Modify `backend/app/api/schemas/order.py` — extend `OrderItemOut` (three new fields) and `OrderItemConfirmIn` (three new optional input fields: `received_price`, `declined`, `decline_reason`).
- Modify `backend/app/allocation/order_service.py` — extend `set_confirmed_price` (or rename/generalize) to apply all patchable fields in one call.
- Modify `backend/app/api/order.py` — thread new fields through `_to_order_item_out` and the PATCH handler.
- Modify `backend/tests/allocation/test_order.py` — new tests for `received_price` PATCH semantics and `declined_at`/`decline_reason` PATCH semantics, including coexistence with `received_price`/`confirmed_price`.
- Modify `frontend/src/api/types.ts` — extend `OrderItem` interface.
- Modify `frontend/src/api/orders.ts` — extend PATCH call to accept the new fields.
- Modify `frontend/src/routes/OrderDetailPage.tsx` — new "Полученная цена" column, new decline control (separate from price cells), decline counter badge.
- Modify `frontend/src/routes/order-detail/OrderDetail.module.css` — styles for the new column/control, reusing existing `discrepantRow`/`danger` tokens for the decline visual state.
- Modify `frontend/src/routes/OrderDetailPage.test.tsx` — tests for the new column and decline control.
- Modify `docs/data-model.md` — update `OrderItem` entity block (also backfills the pre-existing ADR-0007 drift: `unit_price` → `quoted_price`/`confirmed_price`/`confirmed_at`, per ADR-0013 "Последствия").
- Modify `docs/ui-reference.md` — new `## 7. Ордер поставщика — сверка цен (OrderDetailPage.tsx)` section.

---

## Task 1: Backend model + migration

**Files:**
- Modify: `backend/app/models/order.py`
- Create: `backend/alembic/versions/<hash>_add_received_price_and_decline_to_order_items.py`
- Test: `backend/tests/allocation/test_order.py` (model-level smoke test folded into Task 2's PATCH tests — no standalone model test needed, the column additions are exercised through the service layer)

**Interfaces:**
- Produces: `OrderItem.received_price: float | None`, `OrderItem.declined_at: datetime | None`, `OrderItem.decline_reason: str | None` — consumed by Task 2 (service), Task 3 (API/schemas), Task 4 (frontend).

- [ ] **Step 1: Confirm current alembic head**

Run: `cd backend && alembic heads`
Expected output: `b15597e509ec (head)`. If different, use the actual head as `down_revision` in Step 3.

- [ ] **Step 2: Add the three columns to the `OrderItem` model**

Edit `backend/app/models/order.py`, inserting after the existing `confirmed_at` column (after line 55, before the `order`/`material` relationships):

```python
    received_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    """Цена, которую поставщик прислал первым, до торга. NULL = ответа ещё
    нет. Независимо от confirmed_price — может быть заполнено без него и
    наоборот. См. ADR-0013."""
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Когда сотрудник явно пометил позицию как "поставщик не может
    выполнить/нет в наличии". NULL = не отмечено (не значит "доступно").
    Не эксклюзивно с received_price/confirmed_price — обе группы полей
    могут быть заполнены одновременно (напр. отказался, но предложил
    замену по другой цене). См. ADR-0013 п.2."""
    decline_reason: Mapped[str | None] = mapped_column(String(500))
    """Свободный текст, необязательный. См. ADR-0013 п.2."""
```

- [ ] **Step 3: Write the migration**

Create `backend/alembic/versions/<hash>_add_received_price_and_decline_to_order_items.py` (generate a real hex revision id, e.g. via `python -c "import uuid; print(uuid.uuid4().hex[:12])"`, don't reuse this placeholder):

```python
"""add received_price and decline fields to order_items (ADR-0013)

Revision ID: <hash>
Revises: b15597e509ec
Create Date: 2026-08-20 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "<hash>"
down_revision: str | None = "b15597e509ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("received_price", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("decline_reason", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "decline_reason")
    op.drop_column("order_items", "declined_at")
    op.drop_column("order_items", "received_price")
```

- [ ] **Step 4: Apply the migration and verify**

Run: `cd backend && alembic upgrade head`
Expected: migration applies cleanly, no errors. Then `alembic heads` should show the new revision as head.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/order.py backend/alembic/versions/
git commit -m "feat: add OrderItem.received_price and decline fields (ADR-0013)"
```

---

## Task 2: Service-layer PATCH logic

**Files:**
- Modify: `backend/app/allocation/order_service.py`
- Test: `backend/tests/allocation/test_order.py`

**Interfaces:**
- Consumes: `OrderItem` model fields from Task 1 (`received_price`, `declined_at`, `decline_reason`).
- Produces: `set_order_item_fields(db: Session, order_id: uuid.UUID, item_id: uuid.UUID, *, confirmed_price: float | None = ..., received_price: float | None = ..., declined: bool | None = ..., decline_reason: str | None = ...) -> OrderItem` — replaces `set_confirmed_price` as the PATCH entry point used by Task 3 (API layer). Uses Python's `...`/sentinel convention (see Step 2 for exact sentinel) to distinguish "field omitted from PATCH" from "field explicitly set to `None`" for every parameter, matching the exact per-field independence PATCH already has for `confirmed_price`.

- [ ] **Step 1: Write failing tests for the new service behavior**

Add to `backend/tests/allocation/test_order.py` (append near `test_set_confirmed_price_sets_and_clears_confirmed_at`):

```python
from app.allocation.order_service import set_order_item_fields


def test_set_order_item_fields_sets_received_price_independent_of_confirmed(
    db_session, make_supplier, make_material, make_price, make_project
):
    """received_price can be set and read back without touching
    confirmed_price/confirmed_at at all — ADR-0013 п.1."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    item = set_order_item_fields(session, orders[0].id, item_id, received_price=4.75)

    assert float(item.received_price) == 4.75
    assert item.confirmed_price is None
    assert item.confirmed_at is None


def test_set_order_item_fields_confirmed_price_allowed_without_received_price(
    db_session, make_supplier, make_material, make_price, make_project
):
    """confirmed_price does not require received_price to be set first —
    ADR-0013 п.1 explicitly allows skipping the "received" step (e.g. phone
    confirmation at quoted_price)."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    item = set_order_item_fields(session, orders[0].id, item_id, confirmed_price=5.00)

    assert item.received_price is None
    assert float(item.confirmed_price) == 5.00
    assert item.confirmed_at is not None


def test_set_order_item_fields_declined_stamps_and_clears_declined_at(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    declined = set_order_item_fields(
        session, orders[0].id, item_id, declined=True, decline_reason="нет в наличии"
    )
    assert declined.declined_at is not None
    assert declined.decline_reason == "нет в наличии"

    undeclined = set_order_item_fields(session, orders[0].id, item_id, declined=False)
    assert undeclined.declined_at is None
    assert undeclined.decline_reason is None


def test_set_order_item_fields_declined_coexists_with_received_and_confirmed_price(
    db_session, make_supplier, make_material, make_price, make_project
):
    """ADR-0013 п.2: declined_at is not mutually exclusive with
    received_price/confirmed_price — "declined, but offered a substitute
    at another price" needs both facts on the same row."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    set_order_item_fields(session, orders[0].id, item_id, received_price=6.50)
    item = set_order_item_fields(
        session, orders[0].id, item_id, declined=True, decline_reason="снят с производства"
    )

    assert item.declined_at is not None
    assert float(item.received_price) == 6.50  # not cleared by declining


def test_set_order_item_fields_omitted_field_leaves_existing_value_untouched(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    set_order_item_fields(session, orders[0].id, item_id, received_price=4.75)
    # Second call only touches confirmed_price; received_price must survive.
    item = set_order_item_fields(session, orders[0].id, item_id, confirmed_price=5.00)

    assert float(item.received_price) == 4.75
    assert float(item.confirmed_price) == 5.00
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/allocation/test_order.py -k set_order_item_fields -v`
Expected: FAIL (`ImportError: cannot import name 'set_order_item_fields'`).

- [ ] **Step 3: Implement `set_order_item_fields`, replacing `set_confirmed_price`**

In `backend/app/allocation/order_service.py`, replace the existing `set_confirmed_price` function (lines 223–237) with:

```python
_UNSET = object()
"""Sentinel distinguishing "field omitted from PATCH" (leave untouched)
from "field explicitly set to None" (clear it) — needed because every new
field on this endpoint is independently optional, same semantics
confirmed_price already had alone. See ADR-0013 п.3."""


def set_order_item_fields(
    db: Session,
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    confirmed_price: float | None = _UNSET,
    received_price: float | None = _UNSET,
    declined: bool | None = _UNSET,
    decline_reason: str | None = _UNSET,
) -> OrderItem:
    """PATCH .../items/{item_id} — see ADR-0007 п.3 and ADR-0013 п.3. Each
    keyword is independently optional: omit it (leave at the _UNSET
    default) to leave that field untouched, or pass None explicitly to
    clear it. declined=True stamps declined_at=now(); declined=False clears
    declined_at and decline_reason together. No field here validates
    against any other — declined_at may coexist with received_price/
    confirmed_price (ADR-0013 п.2), and confirmed_price may be set without
    received_price ever being set (ADR-0013 п.1)."""
    item = db.get(OrderItem, item_id)
    if item is None or item.order_id != order_id:
        raise OrderItemNotFoundError(order_id, item_id)

    if confirmed_price is not _UNSET:
        item.confirmed_price = confirmed_price
        item.confirmed_at = datetime.now(timezone.utc) if confirmed_price is not None else None

    if received_price is not _UNSET:
        item.received_price = received_price

    if declined is not _UNSET:
        if declined:
            item.declined_at = datetime.now(timezone.utc)
        else:
            item.declined_at = None
            item.decline_reason = None

    if decline_reason is not _UNSET:
        item.decline_reason = decline_reason

    db.commit()
    db.refresh(item)
    return item
```

Note: `decline_reason` is applied independently of `declined` (per ADR-0013 §3 — "decline_reason передаётся отдельным опциональным полем... применяется независимо от declined"), except that `declined=False` always clears it as part of un-declining, applied before the standalone `decline_reason` branch would run in the same call (in practice a single PATCH call won't send both `declined=False` and a `decline_reason` — the API layer in Task 3 passes through whatever the client sent, this ordering just keeps the un-declining path deterministic if it ever happens).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/allocation/test_order.py -v`
Expected: all tests PASS, including the pre-existing `test_set_confirmed_price_sets_and_clears_confirmed_at` (Task 3 will update its call site — this test currently calls the API endpoint via `client.patch`, not the service function directly, so it stays green through this task unmodified).

- [ ] **Step 5: Commit**

```bash
git add backend/app/allocation/order_service.py backend/tests/allocation/test_order.py
git commit -m "feat: generalize OrderItem PATCH service to received_price/decline fields (ADR-0013)"
```

---

## Task 3: API schemas + endpoint wiring

**Files:**
- Modify: `backend/app/api/schemas/order.py`
- Modify: `backend/app/api/order.py`
- Test: `backend/tests/allocation/test_order.py`

**Interfaces:**
- Consumes: `set_order_item_fields` from Task 2.
- Produces: `OrderItemOut` with `received_price`, `declined_at`, `decline_reason` fields; `OrderItemConfirmIn` with the same three as optional input fields — consumed by Task 4 (frontend types must match these field names exactly).

- [ ] **Step 1: Write failing API-level tests**

Add to `backend/tests/allocation/test_order.py`:

```python
def test_patch_order_item_sets_received_price_via_api(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    response = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}", json={"received_price": 4.90}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["received_price"] == 4.90
    assert body["confirmed_price"] is None


def test_patch_order_item_declines_via_api(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    response = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}",
        json={"declined": True, "decline_reason": "нет в наличии"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["declined_at"] is not None
    assert body["decline_reason"] == "нет в наличии"

    undeclined = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}", json={"declined": False}
    )
    assert undeclined.status_code == 200
    undeclined_body = undeclined.json()
    assert undeclined_body["declined_at"] is None
    assert undeclined_body["decline_reason"] is None


def test_patch_order_item_partial_payload_leaves_other_fields_untouched_via_api(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)
    item_id = orders[0].items[0].id

    client.patch(f"/orders/{orders[0].id}/items/{item_id}", json={"received_price": 4.90})
    response = client.patch(
        f"/orders/{orders[0].id}/items/{item_id}", json={"confirmed_price": 5.00}
    )

    body = response.json()
    assert body["received_price"] == 4.90
    assert body["confirmed_price"] == 5.00
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/allocation/test_order.py -k "received_price_via_api or declines_via_api or partial_payload" -v`
Expected: FAIL — `OrderItemOut`/`OrderItemConfirmIn` don't have these fields yet (422 or KeyError on response body assertions).

- [ ] **Step 3: Extend the Pydantic schemas**

Edit `backend/app/api/schemas/order.py`. Replace the `OrderItemOut` class body and `OrderItemConfirmIn` class:

```python
class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    material_id: uuid.UUID
    quantity: int
    quoted_price: float
    received_price: float | None = None
    confirmed_price: float | None = None
    confirmed_at: datetime | None = None
    declined_at: datetime | None = None
    decline_reason: str | None = None
    price_delta: float | None = None
    price_delta_pct: float | None = None


class OrderItemConfirmIn(BaseModel):
    """Body for PATCH /orders/{order_id}/items/{item_id} — see ADR-0007 п.3
    and ADR-0013 п.3. Every field is independently optional: omitting a
    field leaves it untouched; passing null explicitly clears it (for
    confirmed_price/received_price) or, for declined, false clears
    declined_at/decline_reason. Field omitted vs field=null is
    distinguished server-side via `model_fields_set` in the API handler,
    not by this schema alone."""

    confirmed_price: float | None = Field(default=None)
    received_price: float | None = Field(default=None)
    declined: bool | None = Field(default=None)
    decline_reason: str | None = Field(default=None)
```

Add `Field` to the existing `from pydantic import BaseModel, ConfigDict` import line, making it `from pydantic import BaseModel, ConfigDict, Field`.

Also update the module docstring at the top of the file to mention the new fields, appending after the existing paragraph:

```python
"""Pydantic-схемы для Order/OrderItem — см. ADR-0007.

quoted_price/confirmed_price — раздельные снимок и сверка, не одно поле
unit_price (переименовано под ADR-0007 п.1). price_delta/price_delta_pct —
вычисляются на чтении (app/allocation/order_service.py), не хранятся в БД.

received_price/declined_at/decline_reason — см. ADR-0013. received_price
не имеет собственного price_delta аналога (ADR-0013 п.4: только quoted vs
confirmed остаётся вычисляемым показателем).
"""
```

- [ ] **Step 4: Wire the endpoint to distinguish omitted vs explicit-null**

`OrderItemConfirmIn` as a flat Pydantic model can't tell "field omitted" from "field explicitly null" using plain attribute access — both read as the Python value on the model. Use FastAPI's raw-body pattern: read `model_fields_set` from the parsed model to know which keys were actually present in the JSON payload, then pass only those through as keyword arguments to `set_order_item_fields`.

Edit `backend/app/api/order.py`. Replace the `_to_order_item_out` function and the PATCH handler:

```python
def _to_order_item_out(item) -> OrderItemOut:
    delta, delta_pct = price_delta(item.quoted_price, item.confirmed_price)
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
    )
```

```python
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
    return _to_order_item_out(item)
```

Update the import at the top of `backend/app/api/order.py` from:

```python
from app.allocation.order_service import (
    DraftOrderConflictError,
    OrderItemNotFoundError,
    RunNotFoundError,
    create_orders_for_run,
    price_delta,
    set_confirmed_price,
)
```

to:

```python
from app.allocation.order_service import (
    DraftOrderConflictError,
    OrderItemNotFoundError,
    RunNotFoundError,
    create_orders_for_run,
    price_delta,
    set_order_item_fields,
)
```

Note the endpoint function is renamed `patch_order_item_confirmed_price` → `patch_order_item` since it now does more than confirm a price; the route path/method/response model are unchanged, so this is not a breaking API change.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/allocation/test_order.py -v`
Expected: all tests PASS, including the pre-existing `test_set_confirmed_price_sets_and_clears_confirmed_at` and `test_patch_order_item_returns_404_for_unknown_order` / `test_patch_order_item_returns_404_for_item_from_different_order` (unaffected by the rename — they hit the route, not the Python function name).

- [ ] **Step 6: Run the full backend test suite and lint**

Run: `cd backend && pytest && ruff check .`
Expected: all tests pass, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/schemas/order.py backend/app/api/order.py backend/tests/allocation/test_order.py
git commit -m "feat: expose received_price/decline fields on Order API (ADR-0013)"
```

---

## Task 4: Frontend types + API client

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/orders.ts`

**Interfaces:**
- Consumes: field names from Task 3's `OrderItemOut`/`OrderItemConfirmIn` (`received_price`, `declined_at`, `decline_reason`).
- Produces: `OrderItem` TS interface with the three new fields; `ordersApi.setItemFields(orderId: string, itemId: string, fields: Partial<{ confirmed_price: number | null; received_price: number | null; declined: boolean; decline_reason: string | null }>) => Promise<OrderItem>` — replaces `ordersApi.setConfirmedPrice`, consumed by Task 5 (OrderDetailPage).

- [ ] **Step 1: Extend the `OrderItem` interface**

Edit `frontend/src/api/types.ts`. Replace the `OrderItem` interface (lines 223–233):

```typescript
export interface OrderItem {
  id: string;
  order_id: string;
  material_id: string;
  quantity: number;
  quoted_price: number;
  received_price: number | null;
  confirmed_price: number | null;
  confirmed_at: string | null;
  declined_at: string | null;
  decline_reason: string | null;
  price_delta: number | null;
  price_delta_pct: number | null;
}
```

- [ ] **Step 2: Replace `setConfirmedPrice` with a general field-setter**

Edit `frontend/src/api/orders.ts`:

```typescript
import { http } from './client';
import type { Order, OrderItem } from './types';

export interface OrderItemPatch {
  confirmed_price?: number | null;
  received_price?: number | null;
  declined?: boolean;
  decline_reason?: string | null;
}

export const ordersApi = {
  createForRun: (projectId: string, runId: string, replaceDrafts = false) =>
    http.post<Order[]>(`/projects/${projectId}/allocations/${runId}/orders`, {
      replace_drafts: replaceDrafts,
    }),
  listForProject: (projectId: string) => http.get<Order[]>(`/projects/${projectId}/orders`),
  get: (orderId: string) => http.get<Order>(`/orders/${orderId}`),
  patchItem: (orderId: string, itemId: string, patch: OrderItemPatch) =>
    http.patch<OrderItem>(`/orders/${orderId}/items/${itemId}`, patch),
};
```

Only the keys present in `patch` are sent as JSON — the caller (Task 5) controls the omitted-vs-null distinction by which keys it includes in the object literal, matching the backend's `model_fields_set` handling from Task 3.

- [ ] **Step 3: Type-check**

Run: `cd frontend && npm run build 2>&1 | grep -i "OrderDetailPage\|orders.ts\|types.ts"` (the build will still fail at this point because `OrderDetailPage.tsx` still calls the now-removed `ordersApi.setConfirmedPrice` — that's expected and fixed in Task 5). Confirm the only errors reported are in `OrderDetailPage.tsx` referencing `setConfirmedPrice`, not in `types.ts`/`orders.ts` themselves.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/orders.ts
git commit -m "feat: add received_price/decline fields to Order frontend API client (ADR-0013)"
```

---

## Task 5: OrderDetailPage UI — received price column + decline control

**Files:**
- Modify: `frontend/src/routes/OrderDetailPage.tsx`
- Modify: `frontend/src/routes/order-detail/OrderDetail.module.css`
- Modify: `frontend/src/routes/OrderDetailPage.test.tsx`

**Interfaces:**
- Consumes: `ordersApi.patchItem` from Task 4, `OrderItem.received_price`/`declined_at`/`decline_reason` from Task 4.

- [ ] **Step 1: Read the existing test file to match its setup/mocking conventions**

Read `frontend/src/routes/OrderDetailPage.test.tsx` in full before writing new tests — reuse its existing mock order/material/supplier fixtures rather than redefining them, and follow its existing pattern for mocking `ordersApi` calls (whatever mocking library/pattern it already uses).

- [ ] **Step 2: Write failing tests for the new column and decline control**

Add tests to `frontend/src/routes/OrderDetailPage.test.tsx` following the file's existing conventions (exact mock setup depends on Step 1's findings) covering:
- The "Полученная цена" column renders `item.received_price` when set, and an empty/placeholder state when `null`.
- Editing the received-price input and blurring calls `ordersApi.patchItem` with `{ received_price: <value> }` only (not `confirmed_price`).
- A "declined" row (mock item with `declined_at` set) renders with the discrepancy-style visual treatment and shows `decline_reason` if present.
- Clicking the decline control on a non-declined row calls `ordersApi.patchItem` with `{ declined: true }`.
- Clicking the decline control on an already-declined row calls `ordersApi.patchItem` with `{ declined: false }` (toggle-off / un-decline).
- The page-level banner shows a count of declined items alongside the existing discrepancy count when `declined_at` is set on at least one item.

Run: `cd frontend && npm run test -- OrderDetailPage`
Expected: FAIL (new assertions reference UI that doesn't exist yet).

- [ ] **Step 3: Implement the received-price column and decline control**

Edit `frontend/src/routes/OrderDetailPage.tsx`.

Replace `handleConfirmedPriceChange` with a general field-patch handler:

```typescript
  async function handleItemPatch(item: OrderItem, patch: OrderItemPatch) {
    if (!data) return;
    setSaveError(null);
    setSavingItemId(item.id);
    try {
      const updated = await ordersApi.patchItem(data.order.id, item.id, patch);
      setData((prev) =>
        prev
          ? {
              ...prev,
              order: {
                ...prev.order,
                items: prev.order.items.map((i) => (i.id === item.id ? updated : i)),
              },
            }
          : prev,
      );
    } catch (err) {
      setSaveError(err);
    } finally {
      setSavingItemId(null);
    }
  }
```

Add the import `import type { OrderItemPatch } from '../api/orders';` alongside the existing `ordersApi` import.

Update the table header (inside `<thead><tr>`) to insert the new column between "Отправленная цена" and "Подтверждённая цена", and add a "Статус" column for the decline control:

```tsx
            <tr>
              <th className={styles.materialColHeader}>Материал</th>
              <th className={styles.numCell}>Кол-во</th>
              <th className={styles.numCell}>Отправленная цена</th>
              <th className={styles.numCell}>Полученная цена</th>
              <th className={styles.numCell}>Подтверждённая цена</th>
              <th className={styles.numCell}>Расхождение</th>
              <th className={styles.statusColHeader}>Статус</th>
            </tr>
```

Update the discrepancy banner section to also report declined items:

```tsx
        {(discrepantCount > 0 || declinedCount > 0) && (
          <div className={styles.discrepancyBanner} role="alert">
            {discrepantCount > 0 && (
              <span>
                ⚠ {discrepantCount} {pluralizePositions(discrepantCount)} с расхождением цены больше{' '}
                {SIGNIFICANT_PRICE_DELTA_PCT}%
              </span>
            )}
            {discrepantCount > 0 && declinedCount > 0 && <span> · </span>}
            {declinedCount > 0 && (
              <span>
                ⚠ {declinedCount} {pluralizePositions(declinedCount)} отклонено поставщиком
              </span>
            )}
          </div>
        )}
```

Add `declinedCount` next to the existing `discrepantCount` computation:

```typescript
  const discrepantCount = order.items.filter(
    (item) => item.price_delta_pct != null && Math.abs(item.price_delta_pct) > SIGNIFICANT_PRICE_DELTA_PCT,
  ).length;
  const declinedCount = order.items.filter((item) => item.declined_at != null).length;
```

Update `<OrderItemRow>` usage to pass the new handler:

```tsx
              <OrderItemRow
                key={item.id}
                item={item}
                material={materialById.get(item.material_id)}
                saving={savingItemId === item.id}
                onPatch={(patch) => void handleItemPatch(item, patch)}
              />
```

Replace the `OrderItemRow` component:

```tsx
function OrderItemRow({
  item,
  material,
  saving,
  onPatch,
}: {
  item: OrderItem;
  material: Material | undefined;
  saving: boolean;
  onPatch: (patch: OrderItemPatch) => void;
}) {
  const isDiscrepant =
    item.price_delta_pct != null && Math.abs(item.price_delta_pct) > SIGNIFICANT_PRICE_DELTA_PCT;
  const isDeclined = item.declined_at != null;
  const rowClassName = [isDiscrepant ? styles.discrepantRow : '', isDeclined ? styles.declinedRow : '']
    .filter(Boolean)
    .join(' ') || undefined;

  return (
    <tr className={rowClassName}>
      <td className={styles.materialColCell}>{material?.canonical_name ?? item.material_id}</td>
      <td className={styles.numCell}>
        {item.quantity} {material?.unit ?? ''}
      </td>
      <td className={styles.numCell}>{formatMoney(item.quoted_price)}</td>
      <td className={styles.numCell}>
        <input
          key={item.received_price ?? 'empty'}
          className={styles.priceInput}
          type="number"
          min="0"
          step="0.01"
          placeholder="—"
          defaultValue={item.received_price ?? ''}
          disabled={saving}
          onBlur={(e) => {
            const raw = e.target.value.trim();
            const value = raw === '' ? null : Number(raw);
            if (value !== item.received_price) onPatch({ received_price: value });
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur();
          }}
        />
      </td>
      <td className={styles.numCell}>
        <input
          key={item.confirmed_price ?? 'empty'}
          className={styles.priceInput}
          type="number"
          min="0"
          step="0.01"
          placeholder="—"
          defaultValue={item.confirmed_price ?? ''}
          disabled={saving}
          onBlur={(e) => {
            const raw = e.target.value.trim();
            const value = raw === '' ? null : Number(raw);
            if (value !== item.confirmed_price) onPatch({ confirmed_price: value });
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur();
          }}
        />
      </td>
      <td className={styles.numCell}>
        {item.price_delta != null && item.price_delta_pct != null ? (
          <span className={isDiscrepant ? styles.deltaDiscrepant : styles.delta}>
            {item.price_delta >= 0 ? '+' : ''}
            {formatMoney(item.price_delta)} ({item.price_delta_pct >= 0 ? '+' : ''}
            {item.price_delta_pct.toFixed(1)}%)
          </span>
        ) : (
          <span className={styles.deltaEmpty}>—</span>
        )}
      </td>
      <td className={styles.statusColCell}>
        <button
          type="button"
          className={isDeclined ? styles.declineButtonActive : styles.declineButton}
          disabled={saving}
          onClick={() => onPatch({ declined: !isDeclined })}
        >
          {isDeclined ? 'Отклонено' : 'Отметить как недоступно'}
        </button>
        {isDeclined && (
          <input
            key={item.decline_reason ?? 'empty'}
            className={styles.declineReasonInput}
            type="text"
            placeholder="Причина (необязательно)"
            defaultValue={item.decline_reason ?? ''}
            disabled={saving}
            onBlur={(e) => {
              const raw = e.target.value.trim();
              const value = raw === '' ? null : raw;
              if (value !== item.decline_reason) onPatch({ decline_reason: value });
            }}
          />
        )}
      </td>
    </tr>
  );
}
```

- [ ] **Step 4: Add CSS for the new elements**

Append to `frontend/src/routes/order-detail/OrderDetail.module.css`:

```css
/* Row-level highlight for declined items — same danger-tint language as
   discrepantRow, applied independently (a row can be both). */
.declinedRow td {
  background: var(--color-danger-tint);
}

.statusColHeader,
.statusColCell {
  width: 14%;
}

.declineButton {
  background: var(--color-control-fill);
  color: var(--color-text);
  border: none;
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-5);
  font-size: var(--text-sm-alt2);
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.declineButton:hover {
  background: var(--color-control-fill-hover);
}

.declineButtonActive {
  background: var(--color-danger-tint);
  color: var(--color-danger-text);
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-5);
  font-size: var(--text-sm-alt2);
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.declineReasonInput {
  display: block;
  margin-top: var(--space-3);
  width: 100%;
  font-size: var(--text-sm-alt);
  color: var(--color-text);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
}
```

Adjust `.materialColHeader`/`.materialColCell` width from `34%` down to `28%` to make room for the new columns (6 data columns + material now, vs 5 before):

```css
.materialColHeader,
.materialColCell {
  width: 28%;
}
```

- [ ] **Step 5: Run frontend tests to verify they pass**

Run: `cd frontend && npm run test -- OrderDetailPage`
Expected: all tests PASS.

- [ ] **Step 6: Run full frontend test suite, lint, and build**

Run: `cd frontend && npm run lint && npm run test && npm run build`
Expected: all pass, no type errors, no lint errors.

- [ ] **Step 7: Manual verification in the browser**

Start the dev server (`npm run dev` in `frontend/`, plus the backend running against a dev DB with the Task 1 migration applied), navigate to an existing `Order`'s detail page (or create one via the allocation flow), and confirm:
- The "Полученная цена" column appears between "Отправленная цена" and "Подтверждённая цена", editable the same way as the confirmed-price column.
- Entering a received price and blurring persists it (reload the page, value survives).
- Clicking "Отметить как недоступно" marks the row visually (danger tint) and reveals the reason input; entering a reason and blurring persists it.
- Clicking the now-"Отклонено" button again un-declines the row and clears the reason input.
- The banner at the top shows both discrepancy and decline counts when both conditions are present on different rows.
- A row can have both a received/confirmed price editable and be declined at the same time (no blocking behavior).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/routes/OrderDetailPage.tsx frontend/src/routes/order-detail/OrderDetail.module.css frontend/src/routes/OrderDetailPage.test.tsx
git commit -m "feat: add received price column and decline control to OrderDetailPage (ADR-0013)"
```

---

## Task 6: Docs sync

**Files:**
- Modify: `docs/data-model.md`
- Modify: `docs/ui-reference.md`
- Modify: `docs/decisions/0013-order-item-received-price-and-decline.md` (status only)

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Update `docs/data-model.md`**

Replace the `OrderItem` entity block (currently lines 132–137, still showing the pre-ADR-0007 `unit_price` shape — this task fixes both the ADR-0007 drift and adds the ADR-0013 fields in one pass):

```
    OrderItem {
        uuid order_id
        uuid material_id
        int quantity
        decimal quoted_price
        decimal received_price "nullable — первый ответ поставщика, до торга"
        decimal confirmed_price "nullable — финальная договорённость"
        datetime confirmed_at "nullable"
        datetime declined_at "nullable — поставщик не может выполнить позицию"
        string decline_reason "nullable, свободный текст"
    }
```

- [ ] **Step 2: Add `docs/ui-reference.md` §7**

Append a new section after the existing `## 6. Статус проекта` section:

```markdown
## 7. Ордер поставщика — сверка цен (`OrderDetailPage.tsx`, `/orders/:id`)

См. ADR-0007 и ADR-0013 для полной архитектурной мотивации; здесь —
только поведение экрана.

- Таблица позиций: Материал, Кол-во, Отправленная цена (`quoted_price`,
  read-only), **Полученная цена** (`received_price`, inline-редактируемая
  ячейка, тот же паттерн save-on-blur/Enter, что и подтверждённая цена),
  Подтверждённая цена (`confirmed_price`, inline-редактируемая), Расхождение
  (`price_delta`/`price_delta_pct`, read-only, только quoted vs confirmed —
  received не участвует в этом расчёте, см. ADR-0013 п.4), Статус (кнопка
  "Отметить как недоступно" / "Отклонено" + опциональное поле причины).
- `received_price` и `confirmed_price` независимы: можно заполнить любое
  из двух без другого, в любом порядке. Не требуется вводить
  `received_price` перед `confirmed_price`.
- Кнопка "Отметить как недоступно" на строке переключает `declined_at`
  (проставляет/снимает); не блокирует и не требует очистки
  `received_price`/`confirmed_price` — позиция может быть одновременно
  отклонена и иметь введённую цену (случай "отказался, но предложил
  замену"). Строка при `declined_at != null` подсвечивается тем же
  danger-tint языком, что и строка с расхождением >10%; обе подсветки
  независимы и могут применяться к одной строке одновременно.
- Баннер над таблицей суммирует оба сигнала отдельно: "N позиций с
  расхождением цены больше 10%" и "N позиций отклонено поставщиком",
  каждый показывается только если счётчик больше нуля.
- `Order.total_amount` не меняется при отметке `declined_at` — остаётся
  планом (что было отправлено поставщику), не пересчитывается по факту
  отказов. Что происходит с отклонённой позицией дальше (перенос на
  другого поставщика и т.п.) — не на этом экране, отдельная задача
  (ADR-0013 "Не в объёме").
```

- [ ] **Step 3: Flip ADR-0013 status to Принято**

Edit `docs/decisions/0013-order-item-received-price-and-decline.md`, change line 3 from `Статус: Предложено` to `Статус: Принято`.

- [ ] **Step 4: Commit**

```bash
git add docs/data-model.md docs/ui-reference.md docs/decisions/0013-order-item-received-price-and-decline.md
git commit -m "docs: sync data-model and ui-reference with received_price/decline (ADR-0013)"
```

---

## Self-Review Notes

- **Spec coverage:** ADR-0013 §1 (received_price, independent ordering) → Tasks 1–2. §2 (declined_at/decline_reason, coexistence) → Tasks 1–2. §3 (PATCH extension, UI behavior: separate decline control) → Tasks 3, 5. §4 (price_delta unchanged, no received-vs-confirmed metric added) → Task 3 (schemas leave `price_delta` computation untouched) and explicitly noted in Task 6 docs. §5 (total_amount unchanged, declined items not excluded from sums, derived counter) → Task 5 (`declinedCount`, no `total_amount` recomputation anywhere in the plan) and Task 6 docs.
- **Placeholder scan:** no TBD/TODO; the one intentional placeholder is the alembic revision hash in Task 1 Step 3, which is standard practice (alembic hashes are generated at migration-creation time, not planning time) and the step includes the exact command to generate a real one.
- **Type consistency:** `set_order_item_fields` (Task 2) signature matches its usage in Task 3's `patch_order_item` (`**kwargs` built from the same four field names: `confirmed_price`, `received_price`, `declined`, `decline_reason`). `OrderItemOut`/`OrderItemConfirmIn` field names (Task 3) match `OrderItem` TS interface and `OrderItemPatch` TS interface field names (Task 4) exactly. `ordersApi.patchItem` (Task 4) is the function Task 5's `handleItemPatch` calls.
