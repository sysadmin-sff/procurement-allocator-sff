# Router Protection, Audit Columns & Test Auth Fixtures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `Depends(require_role("admin"))`/`Depends(get_current_user)` onto the router-level `APIRouter(...)` of all 9 previously-unauthenticated business routers, add the four `*_user_id` audit FK columns from ADR-0024 §6, and update every existing API test to use an authenticated `TestClient` — closing the gap left intentionally open by the auth-foundation plan (`docs/superpowers/plans/2026-08-26-auth-oauth-foundation.md`).

**Architecture:** No new subsystems. `get_current_user`/`require_role` already exist and are proven correct (`app/auth/dependencies.py`, `backend/tests/auth/`) — this plan only *applies* them at `APIRouter(dependencies=[...])` construction sites, exactly as `user.py` already does. Audit columns are four independent nullable FK additions (one shared Alembic migration) plus one call-site assignment each at the four points that create/mutate the audited rows. Test fixtures duplicate the proven `make_user`/`make_session` pattern from `tests/auth/conftest.py` into each of the 9 affected test modules' own `conftest.py` (this repo's existing convention — no shared root conftest), plus a shared `_client_as(user_session)` helper duplicated per file following the exact pattern already in `tests/user/test_api.py`.

**Tech Stack:** FastAPI (`APIRouter(dependencies=...)`), SQLAlchemy 2.0, Alembic, pytest + `fastapi.testclient.TestClient`.

**Spec:** `docs/decisions/0024-authentication-authorization.md` (ADR-0024) — this plan implements the remainder of §4/§5 (permission matrix + router wiring for the 9 business routers — `user.py`/`auth.py` already done in part 1) and all of §6 (audit columns). §7 (frontend) and §10 (rate limiting) remain out of scope, unchanged from part 1.

## Global Constraints

- Apply `dependencies=[Depends(...)]` on the `APIRouter(...)` construction line itself, never per-endpoint (ADR-0024 §5).
- Do not touch `main.py`'s `app.include_router(...)` calls — protection lives in the router definition, not the mount point (ADR-0024 §5).
- Do not touch anything in `frontend/` — explicitly deferred to a follow-up task; the existing frontend will break against these changes and that is expected.
- `Project.created_by` (`String`) is **removed**, not kept alongside the new column — one Alembic migration drops it and adds `created_by_user_id` (ADR-0024 §6). `POST /projects` stops accepting `created_by` in its payload.
- `Order.created_by_user_id`, `PurchaseRecord.created_by_user_id`, `AllocationLine.overridden_by_user_id` are all nullable FK → `users.id`, added in the same migration as the `Project` column swap.
- `AllocationLine.overridden_by_user_id` must be set on **both** override paths: `override_allocation_line_supplier` (`app/allocation/service.py`) and `replace_and_sync_order` (`app/allocation/order_service.py`, which itself calls `override_allocation_line_supplier` internally — verify one assignment covers both, don't double-write).
- Every existing `test_*.py` file that drives a protected router through `TestClient` must gain an authenticated session; unauthenticated calls should now assert `401`/`403` instead of being removed. Do not delete existing behavioral test coverage — only add auth to the client and add new auth-specific tests alongside it.
- `ruff check .` and `pytest` must pass after every task.
- CSRF: any test issuing `POST`/`PUT`/`PATCH`/`DELETE` through an authenticated client must set `X-CSRF-Token` matching the session's `csrf_token`, or the call will 403 before reaching business logic (`app/auth/dependencies.py:42-44`).

---

## File Structure

```
backend/
  app/
    api/
      supplier.py                        — MODIFY: dependencies=[Depends(require_role("admin"))] on APIRouter(...)
      material.py                        — MODIFY: same
      price.py                           — MODIFY: same
      price_ingestion.py                 — MODIFY: same (router currently has no prefix/kwargs at all)
      user.py                            — NO CHANGE (already correct — confirm only)
      project.py                         — MODIFY: dependencies=[Depends(get_current_user)]; create_project takes current_user, drops created_by from payload
      allocation.py                      — MODIFY: dependencies=[Depends(get_current_user)]; override endpoint passes current_user.id through
      order.py                           — MODIFY: dependencies=[Depends(get_current_user)] (router currently has no prefix/kwargs); create_orders/replace_and_order pass current_user.id through
      purchase_record.py                 — MODIFY: dependencies=[Depends(get_current_user)]; create_record passes current_user.id through
      schemas/
        project.py                       — MODIFY: ProjectCreate drops created_by; ProjectOut created_by -> created_by_user_id
    models/
      project.py                         — MODIFY: created_by (String) -> created_by_user_id (FK -> users.id, nullable)
      order.py                           — MODIFY: Order gains created_by_user_id (FK, nullable)
      purchase_record.py                 — MODIFY: PurchaseRecord gains created_by_user_id (FK, nullable)
      allocation.py                      — MODIFY: AllocationLine gains overridden_by_user_id (FK, nullable)
    allocation/
      service.py                         — MODIFY: override_allocation_line_supplier gains overridden_by_user_id param, sets it
      order_service.py                   — MODIFY: create_orders_for_run gains created_by_user_id param, sets Order.created_by_user_id; replace_and_sync_order gains overridden_by_user_id param, forwards to override_allocation_line_supplier
    purchase_records/
      service.py                         — MODIFY: create_purchase_record gains created_by_user_id param, sets it
  alembic/versions/
    <hash>_add_audit_user_fk_columns.py  — CREATE: drop projects.created_by, add projects.created_by_user_id, orders.created_by_user_id, purchase_records.created_by_user_id, allocation_lines.overridden_by_user_id (all nullable FK -> users.id)
  tests/
    supplier/conftest.py                 — MODIFY: add make_admin_user/make_employee_user/make_session (or reuse pattern) + _client_as helper access
    supplier/test_api.py                 — MODIFY: authenticate client, add 401/403/200 triad tests
    material/conftest.py                 — MODIFY: same pattern
    material/test_api.py                 — MODIFY: same
    price/conftest.py                    — MODIFY: same pattern
    price/test_api.py                    — MODIFY: same
    price_ingestion/conftest.py          — MODIFY: same pattern
    price_ingestion/test_api.py          — MODIFY: same
    project/conftest.py                  — MODIFY: same pattern; make_project drops created_by kwarg or repoints it
    project/test_api.py                  — MODIFY: same + created_by_user_id assertions
    allocation/conftest.py               — MODIFY: same pattern
    allocation/test_api.py               — MODIFY: same
    allocation/test_order.py             — MODIFY: authenticate client
    allocation/test_order_draft_conflict.py — MODIFY: authenticate client
    allocation/test_replace_and_order.py — MODIFY: authenticate client
    purchase_record/conftest.py          — MODIFY: same pattern
    purchase_record/test_api.py          — MODIFY: same
```

---

## Task 1: Audit-column migration + model changes

**Files:**
- Modify: `backend/app/models/project.py`
- Modify: `backend/app/models/order.py`
- Modify: `backend/app/models/purchase_record.py`
- Modify: `backend/app/models/allocation.py`
- Create: `backend/alembic/versions/<hash>_add_audit_user_fk_columns.py`
- Test: `backend/tests/scripts/test_migrations.py` if it exists (check first — run full migration up/down as verification either way)

**Interfaces:**
- Produces: `Project.created_by_user_id: Mapped[uuid.UUID | None]`, `Order.created_by_user_id: Mapped[uuid.UUID | None]`, `PurchaseRecord.created_by_user_id: Mapped[uuid.UUID | None]`, `AllocationLine.overridden_by_user_id: Mapped[uuid.UUID | None]` — all FK to `users.id`, all nullable, all consumed by Task 3.

- [ ] **Step 1: Modify `app/models/project.py`** — replace the `created_by` column:

```python
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.allocation import AllocationRun
    from app.models.material import Material
    from app.models.order import Order
    from app.models.user import User


class Project(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    """Kто создал проект — заполняется из Depends(get_current_user) в
    POST /projects. Nullable ради строк, созданных до ADR-0024. Заменяет
    прежнюю String-колонку created_by, которую ни один вызывающий код
    никогда не заполнял. См. ADR-0024 §6."""
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    items: Mapped[list["ProjectItem"]] = relationship(back_populates="project")
    allocation_runs: Mapped[list["AllocationRun"]] = relationship(back_populates="project")
    orders: Mapped[list["Order"]] = relationship(back_populates="project")
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_user_id])


class ProjectItem(UUIDPKMixin, Base):
    __tablename__ = "project_items"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(nullable=False)

    project: Mapped["Project"] = relationship(back_populates="items")
    material: Mapped["Material"] = relationship(back_populates="project_items")
```

- [ ] **Step 2: Modify `app/models/order.py`** — add `created_by_user_id` to `Order` (add `ForeignKey` import stays, add to `TYPE_CHECKING` block, add column + relationship after `file_ref`):

```python
if TYPE_CHECKING:
    from app.models.material import Material
    from app.models.project import Project
    from app.models.supplier import Supplier
    from app.models.user import User


class Order(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    """draft/approved/sent"""
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    delivery_fee: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    file_ref: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    """Кто создал этот Order — заполняется в create_orders_for_run. Nullable
    ради строк, созданных до ADR-0024. См. ADR-0024 §6."""

    project: Mapped["Project"] = relationship(back_populates="orders")
    supplier: Mapped["Supplier"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_user_id])
```

Leave `OrderItem` unchanged.

- [ ] **Step 3: Modify `app/models/purchase_record.py`** — add `created_by_user_id`:

```python
if TYPE_CHECKING:
    from app.models.material import Material
    from app.models.project import Project
    from app.models.supplier import Supplier
    from app.models.user import User


class PurchaseRecord(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "purchase_records"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    """Название, как его вводит сотрудник, глядя на счёт/переписку поставщика.
    Не обязано матчиться на Material.canonical_name или SupplierMaterialAlias
    — см. ADR-0008 п.1."""
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    material_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("materials.id")
    )
    """Опциональная, не блокирующая аннотация — сотрудник ставит вручную, если
    узнаёт материал. Не участвует ни в каком расчёте этого ADR. См. ADR-0008 п.1."""
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    """Кто внёс эту запись о фактической закупке — заполняется в
    create_purchase_record. Nullable ради строк, созданных до ADR-0024.
    См. ADR-0024 §6."""

    project: Mapped["Project"] = relationship()
    supplier: Mapped["Supplier"] = relationship()
    material: Mapped["Material | None"] = relationship()
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_user_id])
```

- [ ] **Step 4: Modify `app/models/allocation.py`** — add `overridden_by_user_id` to `AllocationLine`, next to `overridden_at`:

```python
if TYPE_CHECKING:
    from app.models.material import Material
    from app.models.project import Project
    from app.models.supplier import Supplier
    from app.models.user import User
```

Add after the `overridden_at` column:

```python
    overridden_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    """Кто выполнил ручной override поставщика этой строки — заполняется в
    override_allocation_line_supplier (оба пути: обычный ручной override и
    replace_and_sync_order). NULL, если overridden_at NULL (строка ни разу
    не переопределялась) или строка создана до ADR-0024. См. ADR-0024 §6."""
```

Add the relationship near the others at the bottom of `AllocationLine`:

```python
    overridden_by: Mapped["User | None"] = relationship(foreign_keys=[overridden_by_user_id])
```

- [ ] **Step 5: Generate and hand-verify the Alembic migration**

Run:
```bash
cd backend && .venv/Scripts/python.exe -m alembic revision --autogenerate -m "add audit user fk columns"
```

Open the generated file and confirm it matches this shape (autogenerate may order operations differently or miss the `postgresql_using`/index details for the dropped column — edit by hand to match exactly, following the style of `18515d737158_add_users_and_sessions.py`):

```python
"""add audit user fk columns

Revision ID: <hash>
Revises: 18515d737158
Create Date: 2026-08-26 ...

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "<hash>"
down_revision: str | None = "18515d737158"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("projects", "created_by")
    op.add_column(
        "projects",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_projects_created_by_user_id_users",
        "projects",
        "users",
        ["created_by_user_id"],
        ["id"],
    )

    op.add_column(
        "orders",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_orders_created_by_user_id_users",
        "orders",
        "users",
        ["created_by_user_id"],
        ["id"],
    )

    op.add_column(
        "purchase_records",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_purchase_records_created_by_user_id_users",
        "purchase_records",
        "users",
        ["created_by_user_id"],
        ["id"],
    )

    op.add_column(
        "allocation_lines",
        sa.Column("overridden_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_allocation_lines_overridden_by_user_id_users",
        "allocation_lines",
        "users",
        ["overridden_by_user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_allocation_lines_overridden_by_user_id_users", "allocation_lines", type_="foreignkey"
    )
    op.drop_column("allocation_lines", "overridden_by_user_id")

    op.drop_constraint(
        "fk_purchase_records_created_by_user_id_users", "purchase_records", type_="foreignkey"
    )
    op.drop_column("purchase_records", "created_by_user_id")

    op.drop_constraint("fk_orders_created_by_user_id_users", "orders", type_="foreignkey")
    op.drop_column("orders", "created_by_user_id")

    op.drop_constraint(
        "fk_projects_created_by_user_id_users", "projects", type_="foreignkey"
    )
    op.drop_column("projects", "created_by_user_id")
    op.add_column("projects", sa.Column("created_by", sa.String(length=255), nullable=True))
```

- [ ] **Step 6: Apply the migration**

Run: `cd backend && .venv/Scripts/python.exe -m alembic upgrade head`
Expected: succeeds, no errors. Then run `.venv/Scripts/python.exe -m alembic downgrade -1 && .venv/Scripts/python.exe -m alembic upgrade head` to prove the downgrade path also works cleanly (required since this migration hand-edits autogenerate output).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/project.py backend/app/models/order.py backend/app/models/purchase_record.py backend/app/models/allocation.py backend/alembic/versions/
git commit -m "feat: add ADR-0024 §6 audit FK columns (Project/Order/PurchaseRecord/AllocationLine)"
```

---

## Task 2: Router-level auth wiring on all 9 business routers

**Files:**
- Modify: `backend/app/api/supplier.py`
- Modify: `backend/app/api/material.py`
- Modify: `backend/app/api/price.py`
- Modify: `backend/app/api/price_ingestion.py`
- Modify: `backend/app/api/project.py`
- Modify: `backend/app/api/allocation.py`
- Modify: `backend/app/api/order.py`
- Modify: `backend/app/api/purchase_record.py`
- Confirm only (no change expected): `backend/app/api/user.py`

**Interfaces:**
- Consumes: `require_role`, `get_current_user` from `app.auth.dependencies` (already implemented, `backend/app/auth/dependencies.py:33` and `:50`).
- Produces: every route in these 9 files now requires a session (401 without one); the 5 admin-only files additionally require `role == "admin"` (403 for employee).

- [ ] **Step 1: `supplier.py`** — add the import and dependency:

```python
from app.auth.dependencies import require_role
```

Change:
```python
router = APIRouter(prefix="/suppliers")
```
to:
```python
router = APIRouter(prefix="/suppliers", dependencies=[Depends(require_role("admin"))])
```

- [ ] **Step 2: `material.py`** — same pattern:

```python
from app.auth.dependencies import require_role
```
```python
router = APIRouter(prefix="/materials", dependencies=[Depends(require_role("admin"))])
```

- [ ] **Step 3: `price.py`** — same pattern:

```python
from app.auth.dependencies import require_role
```
```python
router = APIRouter(prefix="/prices", dependencies=[Depends(require_role("admin"))])
```

- [ ] **Step 4: `price_ingestion.py`** — router currently has no prefix or kwargs at all:

```python
from app.auth.dependencies import require_role
```
```python
router = APIRouter(dependencies=[Depends(require_role("admin"))])
```

- [ ] **Step 5: Run ruff + a quick smoke import to confirm no circular imports**

Run: `cd backend && .venv/Scripts/python.exe -m ruff check app/api/supplier.py app/api/material.py app/api/price.py app/api/price_ingestion.py`
Expected: no errors.

Run: `cd backend && .venv/Scripts/python.exe -c "from app.main import app"`
Expected: no exception.

- [ ] **Step 6: Commit the four admin-only routers**

```bash
git add backend/app/api/supplier.py backend/app/api/material.py backend/app/api/price.py backend/app/api/price_ingestion.py
git commit -m "feat: require admin role on supplier/material/price/price_ingestion routers"
```

- [ ] **Step 7: `project.py`** — add `get_current_user`, wire router-level dependency, and thread the authenticated user into `create_project` (this also removes the `created_by` payload field per Task 3's schema change — but do the dependency wiring here; the schema/service body edit is Task 3 since it depends on the audit column):

```python
from app.auth.dependencies import get_current_user
```
```python
router = APIRouter(prefix="/projects", dependencies=[Depends(get_current_user)])
```

- [ ] **Step 8: `allocation.py`** — same dependency pattern:

```python
from app.auth.dependencies import get_current_user
```
```python
router = APIRouter(prefix="/projects/{project_id}", dependencies=[Depends(get_current_user)])
```

- [ ] **Step 9: `order.py`** — router currently has no prefix/kwargs:

```python
from app.auth.dependencies import get_current_user
```
```python
router = APIRouter(dependencies=[Depends(get_current_user)])
```

- [ ] **Step 10: `purchase_record.py`** — same pattern:

```python
from app.auth.dependencies import get_current_user
```
```python
router = APIRouter(
    prefix="/projects/{project_id}/purchase-records", dependencies=[Depends(get_current_user)]
)
```

- [ ] **Step 11: Confirm `user.py` already matches (no edit expected)**

Run: `grep -n "router = APIRouter" backend/app/api/user.py`
Expected output: `router = APIRouter(prefix="/users", dependencies=[Depends(require_role("admin"))])` — already correct from part 1, this step is verification only, not a change.

- [ ] **Step 12: Smoke import + ruff**

Run: `cd backend && .venv/Scripts/python.exe -c "from app.main import app"`
Expected: no exception (tests will fail at this point until Task 3/4 land — that's expected, don't run pytest yet).

Run: `cd backend && .venv/Scripts/python.exe -m ruff check app/api/project.py app/api/allocation.py app/api/order.py app/api/purchase_record.py`
Expected: no errors.

- [ ] **Step 13: Commit the four `get_current_user` routers**

```bash
git add backend/app/api/project.py backend/app/api/allocation.py backend/app/api/order.py backend/app/api/purchase_record.py
git commit -m "feat: require authenticated session on project/allocation/order/purchase_record routers"
```

---

## Task 3: Thread audit user IDs through service calls

**Files:**
- Modify: `backend/app/api/schemas/project.py`
- Modify: `backend/app/api/project.py`
- Modify: `backend/app/allocation/service.py`
- Modify: `backend/app/allocation/order_service.py`
- Modify: `backend/app/api/allocation.py`
- Modify: `backend/app/api/order.py`
- Modify: `backend/app/purchase_records/service.py`
- Modify: `backend/app/api/purchase_record.py`

**Interfaces:**
- Consumes: `Task 1`'s new model columns; `Task 2`'s router-level `Depends(get_current_user)` (endpoint functions can now add a `current_user: User = Depends(get_current_user)` parameter — FastAPI resolves it once per request even though the router-level dependency already ran it, same object via its own dependency cache).
- Produces: `override_allocation_line_supplier(db, run_id, line_id, new_supplier_id, source_order_item_id=None, overridden_by_user_id=None)`; `create_orders_for_run(db, project_id, run_id, replace_drafts=False, created_by_user_id=None)`; `replace_and_sync_order(db, order_id, item_id, supplier_id, overridden_by_user_id=None)`; `create_purchase_record(db, project_id, supplier_id, raw_description, quantity, unit_price, material_id, created_by_user_id=None)`.

- [ ] **Step 1: `app/api/schemas/project.py`** — drop `created_by` from `ProjectCreate`, rename the field on `ProjectOut`:

```python
class ProjectCreate(BaseModel):
    title: str


class ProjectUpdate(BaseModel):
    title: str


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_by_user_id: uuid.UUID | None
    status: str
    created_at: datetime
```

- [ ] **Step 2: `app/api/project.py`** — `create_project` takes the current user and stops reading `created_by` from the payload:

```python
from app.auth.dependencies import get_current_user
```

```python
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
```

Add `from app.models import ... User` to the existing `app.models` import line (check current import list first — it already imports several model names on one line; add `User` to it).

- [ ] **Step 3: `app/allocation/service.py`** — `override_allocation_line_supplier` gains the new parameter and sets it:

```python
def override_allocation_line_supplier(
    db: Session,
    run_id: uuid.UUID,
    line_id: uuid.UUID,
    new_supplier_id: uuid.UUID,
    source_order_item_id: uuid.UUID | None = None,
    overridden_by_user_id: uuid.UUID | None = None,
) -> AllocationLine:
```

In the body, alongside the existing:
```python
    line.overridden_at = datetime.now(timezone.utc)
    line.overridden_via_order_item_id = source_order_item_id
```
add:
```python
    line.overridden_by_user_id = overridden_by_user_id
```

Keep the default `None` so `replace_and_sync_order`'s internal call and any other caller that doesn't pass it stays valid — but Task 3 Step 5 below updates `replace_and_sync_order` itself to forward its own new parameter through, so in practice both call sites will pass a real value once wired end-to-end.

- [ ] **Step 4: `app/api/allocation.py`** — pass `current_user.id` through the override endpoint:

```python
from app.auth.dependencies import get_current_user
```

```python
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
        ...  # unchanged — keep existing except block(s) below this line as-is
```

Add `User` to the `app.models` import in this file (check current import list — it imports `AllocationRun, Project`; add `User`).

- [ ] **Step 5: `app/allocation/order_service.py`** — `create_orders_for_run` gains the parameter and sets `Order.created_by_user_id`:

```python
def create_orders_for_run(
    db: Session,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    replace_drafts: bool = False,
    created_by_user_id: uuid.UUID | None = None,
) -> list[Order]:
```

In the loop that builds each `Order`, add the field:
```python
        order = Order(
            project_id=project_id,
            supplier_id=supplier_id,
            status="draft",
            total_amount=sum(float(line.line_total) for line in lines),
            delivery_fee=summary["delivery_fee"],
            created_by_user_id=created_by_user_id,
        )
```

- [ ] **Step 6: `app/allocation/order_service.py`** — `replace_and_sync_order` gains the parameter and forwards it to `override_allocation_line_supplier`:

```python
def replace_and_sync_order(
    db: Session,
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    supplier_id: uuid.UUID,
    overridden_by_user_id: uuid.UUID | None = None,
) -> OrderItem:
```

In the body, update the existing call:
```python
    line = override_allocation_line_supplier(
        db,
        run_id=line_before.allocation_run_id,
        line_id=line_id,
        new_supplier_id=supplier_id,
        source_order_item_id=item_id,
        overridden_by_user_id=overridden_by_user_id,
    )
```

This is the "both paths" requirement from ADR-0024 §6 satisfied by one shared implementation — `replace_and_sync_order` never sets `overridden_by_user_id` on the line itself, it always delegates to `override_allocation_line_supplier`, so Step 3's single assignment covers both call sites. Do not add a second, separate assignment in `replace_and_sync_order` — that would be dead code shadowed by the delegated call.

- [ ] **Step 7: `app/api/order.py`** — pass `current_user.id` through `create_orders` and `replace_and_order`:

```python
from app.auth.dependencies import get_current_user
```

```python
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
```

```python
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
        ...  # unchanged — keep the remaining except block(s) as-is
```

Add `User` to this file's `app.models` import (check current import list first).

- [ ] **Step 8: `app/purchase_records/service.py`** — `create_purchase_record` gains the parameter:

```python
def create_purchase_record(
    db: Session,
    project_id: uuid.UUID,
    supplier_id: uuid.UUID,
    raw_description: str,
    quantity: int,
    unit_price: float,
    material_id: uuid.UUID | None,
    created_by_user_id: uuid.UUID | None = None,
) -> PurchaseRecord:
    record = PurchaseRecord(
        project_id=project_id,
        supplier_id=supplier_id,
        raw_description=raw_description,
        quantity=quantity,
        unit_price=unit_price,
        material_id=material_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
```

- [ ] **Step 9: `app/api/purchase_record.py`** — pass `current_user.id` through:

```python
from app.auth.dependencies import get_current_user
```

```python
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
```

Add `User` to this file's `app.models` import (currently imports `Project, PurchaseRecord`).

- [ ] **Step 10: Smoke import + ruff**

Run: `cd backend && .venv/Scripts/python.exe -c "from app.main import app"`
Expected: no exception.

Run: `cd backend && .venv/Scripts/python.exe -m ruff check app/`
Expected: no errors (existing tests will still fail — that's fixed in Task 4).

- [ ] **Step 11: Commit**

```bash
git add backend/app/api/schemas/project.py backend/app/api/project.py backend/app/allocation/service.py backend/app/allocation/order_service.py backend/app/api/allocation.py backend/app/api/order.py backend/app/purchase_records/service.py backend/app/api/purchase_record.py
git commit -m "feat: thread ADR-0024 §6 audit user IDs through project/order/allocation/purchase-record writes"
```

---

## Task 4: Authenticated test fixtures + updated existing tests — supplier, material, price, price_ingestion

**Files:**
- Modify: `backend/tests/supplier/conftest.py`
- Modify: `backend/tests/supplier/test_api.py`
- Modify: `backend/tests/material/conftest.py`
- Modify: `backend/tests/material/test_api.py`
- Modify: `backend/tests/price/conftest.py`
- Modify: `backend/tests/price/test_api.py`
- Modify: `backend/tests/price_ingestion/conftest.py`
- Modify: `backend/tests/price_ingestion/test_api.py`

**Interfaces:**
- Consumes: `app.auth.constants.SESSION_IDLE_TTL`, `app.models.User`/`UserSession` (same imports `tests/auth/conftest.py` already uses).
- Produces: each of these 4 conftests exposes `make_user`, `make_session` fixtures (same signatures as `tests/auth/conftest.py`); each corresponding `test_api.py` exposes a module-level `_client_as(user_session)` helper and an authenticated admin client for every existing call site, plus new 401/403/200 triad tests.

This task is mechanical and repeats 4 times — one sub-task per router. Each router in this task is `admin`-only, so every existing test needs an **admin** session; no employee-role happy path exists for these 4 files (403 tests use an employee session deliberately, to prove the role check works).

- [ ] **Step 1: Add auth fixtures to `tests/supplier/conftest.py`**

Read the current file first (it has its own `db_session`/`make_supplier` etc. with its own cleanup lists). Add these fixtures using the *same* `db_session` fixture already defined there — do not create a second `db_session` fixture in the same file, extend the existing one's cleanup to also track `user_ids` and delete `User`/`UserSession` rows on teardown, mirroring `tests/auth/conftest.py`'s teardown order (delete `UserSession` before `User`, both before commit):

```python
import uuid as _uuid  # only if `uuid` isn't already imported — check first
from datetime import datetime, timedelta, timezone

from app.auth.constants import SESSION_IDLE_TTL
from app.models import User, UserSession  # merge into existing app.models import if present
```

Extend the existing `db_session` fixture's teardown to also clean up `user_ids` (add `user_ids: list = []` alongside the file's other id lists, and add the `UserSession`-then-`User` delete block before the final `session.commit()`, same pattern as `tests/auth/conftest.py:12-33`).

Add:
```python
@pytest.fixture
def make_user(db_session):
    session, *rest = db_session
    user_ids = rest[-1]  # the newly-added user_ids list — adjust unpacking to match this file's actual db_session yield shape

    def _make(
        email="employee@screen-factory-florida.com",
        google_sub=None,
        role="employee",
        is_active=True,
        name="Test User",
    ):
        user = User(email=email, google_sub=google_sub, role=role, is_active=is_active, name=name)
        session.add(user)
        session.flush()
        user_ids.append(user.id)
        return user

    return _make


@pytest.fixture
def make_session(db_session):
    session, *_ = db_session

    def _make(user, csrf_token="test-csrf-token"):
        now = datetime.now(timezone.utc)
        user_session = UserSession(
            id=_uuid.uuid4(),
            user_id=user.id,
            csrf_token=csrf_token,
            created_at=now,
            expires_at=now + SESSION_IDLE_TTL,
            last_seen_at=now,
        )
        session.add(user_session)
        session.flush()
        return user_session

    return _make
```

**Important:** the exact tuple-unpacking of `db_session`'s yield varies per file (some yield `session, ids` as a 2-tuple, others `session, a_ids, b_ids, c_ids`). Read each file's actual `db_session` fixture before writing `make_user`/`make_session` against it — match its real shape, don't guess. Prefer adding `user_ids` as a new trailing element and unpacking with `*rest` then `rest[-1]`, or name every element explicitly if the file already does that.

- [ ] **Step 2: Update `tests/supplier/test_api.py` to use an authenticated client**

Read the full file first. Replace the module-level `client = TestClient(app)` with a local helper (following `tests/user/test_api.py`'s pattern exactly):

```python
from fastapi.testclient import TestClient

from app.main import app


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client
```

For every existing test function: add `make_user, make_session` to its parameter list, create an admin user/session at the top of the test body, replace bare `client.get/post/patch/delete(...)` calls with `_client_as(admin_session).get/post/patch/delete(...)`, and add `headers={"X-CSRF-Token": <token>}` to every mutating call (`post`/`patch`/`put`/`delete`), matching whatever `csrf_token` was passed to `make_session`.

Add these new tests at the end of the file (one triad per representative endpoint — pick the router's primary list/create endpoints, not every single one):

```python
def test_list_suppliers_no_session_returns_401():
    client = TestClient(app)
    response = client.get("/suppliers")
    assert response.status_code == 401


def test_list_suppliers_as_employee_returns_403(make_user, make_session):
    employee = make_user(role="employee")
    employee_session = make_session(employee)
    response = _client_as(employee_session).get("/suppliers")
    assert response.status_code == 403


def test_list_suppliers_as_admin_succeeds(make_user, make_session):
    admin = make_user(email="admin-supplier-list@screen-factory-florida.com", role="admin")
    admin_session = make_session(admin)
    response = _client_as(admin_session).get("/suppliers")
    assert response.status_code == 200
```

Adjust the endpoint path/assertions to match this file's actual primary GET route if `/suppliers` isn't it — check the file's existing tests for the real base path first.

- [ ] **Step 3: Run this file's tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/supplier/ -v`
Expected: all pass.

- [ ] **Step 4: Repeat Steps 1-3 for `material`**

Same pattern against `tests/material/conftest.py` + `tests/material/test_api.py`. Primary endpoint for the new triad: whatever this file's first/simplest `GET` is (check — likely `/materials/search` needs a query param, so prefer a plain list/get-by-id route if one exists, otherwise adapt the triad to use `/materials/search?q=xx`).

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/material/ -v`
Expected: all pass.

- [ ] **Step 5: Repeat Steps 1-3 for `price`**

Same pattern against `tests/price/conftest.py` + `tests/price/test_api.py`.

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/price/ -v`
Expected: all pass.

- [ ] **Step 6: Repeat Steps 1-3 for `price_ingestion`**

Same pattern against `tests/price_ingestion/conftest.py` + `tests/price_ingestion/test_api.py`. This router has no `prefix` (routes are `/suppliers/{id}/price-lists`, `/price-list-imports/**`) — use one of those exact paths for the new triad, matching what the existing tests in this file already call.

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/price_ingestion/ -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/supplier/ backend/tests/material/ backend/tests/price/ backend/tests/price_ingestion/
git commit -m "test: authenticate admin-only router tests (supplier/material/price/price_ingestion)"
```

---

## Task 5: Authenticated test fixtures + updated existing tests — project, allocation (incl. order sub-tests), purchase_record

**Files:**
- Modify: `backend/tests/project/conftest.py`
- Modify: `backend/tests/project/test_api.py`
- Modify: `backend/tests/allocation/conftest.py`
- Modify: `backend/tests/allocation/test_api.py`
- Modify: `backend/tests/allocation/test_order.py`
- Modify: `backend/tests/allocation/test_order_draft_conflict.py`
- Modify: `backend/tests/allocation/test_replace_and_order.py`
- Modify: `backend/tests/purchase_record/conftest.py`
- Modify: `backend/tests/purchase_record/test_api.py`

**Interfaces:**
- Consumes: same `make_user`/`make_session` pattern as Task 4, but these 4 routers only require `get_current_user` (any authenticated role, not just admin) — the 403 case here doesn't exist for role reasons; only the "no session -> 401" case applies, since `employee` is a *valid* role for all of these routes.

- [ ] **Step 1: Add auth fixtures to `tests/project/conftest.py`**

Same mechanical pattern as Task 4 Step 1 — read the actual `db_session` fixture shape first (shown earlier: `session, project_ids, material_ids, supplier_ids`), add `user_ids` tracking and `make_user`/`make_session` fixtures.

Additionally: `make_project`'s signature currently takes `created_by=None` and passes it straight to `Project(created_by=...)`. Since Task 1/3 renamed this to `created_by_user_id`, update `make_project` to match:

```python
def _make(items=None, title="Test Project", created_by_user_id=None, status="draft"):
    project = Project(title=title, created_by_user_id=created_by_user_id, status=status)
    ...
```

Search this test module (and any other file importing `make_project`) for callers passing `created_by=` and update them to `created_by_user_id=`.

- [ ] **Step 2: Update `tests/project/test_api.py`**

Same mechanical pattern as Task 4 Step 2, but since `project.py` uses `get_current_user` (not `require_role`), the client just needs any valid session — default `make_user()` (role `employee`) is enough for the 200-path tests. Also update any existing test that asserts on `ProjectOut.created_by` (string) — it must now assert on `created_by_user_id` (uuid) instead. Search for `"created_by"` in this file specifically:

```bash
grep -n "created_by" backend/tests/project/test_api.py
```

Update each hit: POST payloads must stop sending `created_by` (schema no longer accepts it — Task 3 Step 1), and response assertions should check `created_by_user_id == str(current_user.id)` where a test creates a project through an authenticated client.

Add the triad:

```python
def test_list_projects_no_session_returns_401():
    client = TestClient(app)
    response = client.get("/projects")
    assert response.status_code == 401


def test_create_project_as_employee_succeeds(make_user, make_session):
    employee = make_user(role="employee")
    employee_session = make_session(employee, csrf_token="csrf-proj-create")
    response = _client_as(employee_session).post(
        "/projects",
        json={"title": "New Project"},
        headers={"X-CSRF-Token": "csrf-proj-create"},
    )
    assert response.status_code == 201
    assert response.json()["created_by_user_id"] == str(employee.id)
```

- [ ] **Step 3: Run project tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/project/ -v`
Expected: all pass.

- [ ] **Step 4: Add auth fixtures to `tests/allocation/conftest.py`**

Same pattern. Read the actual fixture shape in this file first (it likely shares similar `make_supplier`/`make_material`/`make_price`/`make_project` fixtures to `tests/project/conftest.py` — check whether `make_project` here also needs the `created_by_user_id` rename from Step 1, independently, since these are separate conftest files per the repo's no-shared-conftest convention).

- [ ] **Step 5: Update `tests/allocation/test_api.py`**

Same mechanical pattern. `allocation.py`'s override endpoint now also records `overridden_by_user_id` — add an assertion in at least one existing override test that the returned line's `overridden_by_user_id` matches the acting user's id (check `AllocationLineOut` schema includes this field first; if it doesn't, that's a gap — add `overridden_by_user_id: uuid.UUID | None` to `AllocationLineOut` in `app/api/schemas/allocation.py` as part of this step, since ADR-0024 §6 audit data should be visible to the API consumer, mirroring how `ProjectOut` was updated in Task 3 Step 1).

Add the standard triad using this router's actual base path (`/projects/{project_id}/allocate` or similar — check the file).

- [ ] **Step 6: Update `tests/allocation/test_order.py`, `test_order_draft_conflict.py`, `test_replace_and_order.py`**

These three files belong to the `order.py` router (no dedicated `tests/order/` directory exists in this repo — confirmed during investigation) and must be updated the same way: replace the module-level unauthenticated `client = TestClient(app)` with `_client_as(session)` per test, using `make_user`/`make_session` from `tests/allocation/conftest.py` (same directory, so these files already have access to that conftest's fixtures without a new import).

For `test_order.py` specifically: it directly imports and calls `create_orders_for_run(db, ...)` and `override_allocation_line_supplier(db, ...)` as service functions in some tests (not just through the API) — these calls don't need auth (they bypass the API layer entirely) but now accept the new `created_by_user_id`/`overridden_by_user_id` kwargs; leave existing direct service calls as-is (default `None` is valid) unless a specific test's assertions specifically check audit fields, in which case pass an explicit test user id and assert on it.

For every test that goes through `TestClient` (i.e., calls `client.post("/projects/.../orders")`, `client.patch(".../items/...")`, etc.), add authentication following the same pattern as prior steps.

- [ ] **Step 7: Run all allocation-directory tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/allocation/ -v`
Expected: all pass.

- [ ] **Step 8: Add auth fixtures to `tests/purchase_record/conftest.py` and update `tests/purchase_record/test_api.py`**

Same mechanical pattern as Steps 1-2. `create_purchase_record` now accepts `created_by_user_id` — if `PurchaseRecordOut` doesn't already expose it, add `created_by_user_id: uuid.UUID | None` to that schema (check `app/api/schemas/purchase_record.py` first) and assert on it in at least one authenticated-create test.

Add the standard triad (401 no-session; 200 as employee, since this router is `get_current_user`-only, no role restriction).

- [ ] **Step 9: Run purchase_record tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/purchase_record/ -v`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add backend/tests/project/ backend/tests/allocation/ backend/tests/purchase_record/ backend/app/api/schemas/allocation.py backend/app/api/schemas/purchase_record.py
git commit -m "test: authenticate project/allocation/order/purchase-record router tests, expose audit fields in API schemas"
```

---

## Task 6: Full-suite verification, checklist reconciliation, and manual 401 proof

**Files:**
- No new files — verification only, plus `docs/data-model.md` and `docs/architecture.md` updates.

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -v`
Expected: all tests pass, including `tests/auth/**` (unaffected) and every file touched in Tasks 4-5.

- [ ] **Step 2: Run ruff over the whole backend**

Run: `cd backend && .venv/Scripts/python.exe -m ruff check .`
Expected: no errors.

- [ ] **Step 3: Run alembic upgrade head against a clean DB to prove migration order**

Run: `cd backend && .venv/Scripts/python.exe -m alembic downgrade base && .venv/Scripts/python.exe -m alembic upgrade head`
Expected: succeeds cleanly through every migration in sequence, ending at the new head.

- [ ] **Step 4: Manual proof — unauthenticated request against a protected route returns 401**

With the dev server running (`cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --reload` in one terminal), from another shell:

```bash
curl -i http://localhost:8000/suppliers
```
Expected: `HTTP/1.1 401 Unauthorized` with body `{"detail":"Not authenticated"}`.

Also verify an admin-only route rejects a non-admin session (403) and an employee-accessible route accepts a valid employee session (200), using a real cookie captured from a logged-in session or a manually-inserted `UserSession` row — whichever is faster to set up. Record the exact command and output for the final report to the user (this is the "live proof" requested in the task instructions, not just pytest coverage).

- [ ] **Step 5: Build and verify the ADR-0024 §5 checklist reconciliation table**

Produce a table with exactly these 11 rows (matching ADR-0024 §5's checklist verbatim) and what was actually applied, for the final report:

| # | File | ADR-0024 §5 requirement | Applied |
|---|------|--------------------------|---------|
| 1 | `health.py` | no changes (public) | confirm unchanged |
| 2 | `auth.py` | `/login`,`/callback` no dependency; `/me`,`/logout` per-endpoint `Depends(get_current_user)` | confirm unchanged (part 1) |
| 3 | `user.py` | `APIRouter(dependencies=[Depends(require_role("admin"))])` | confirm unchanged (part 1) |
| 4 | `supplier.py` | add `dependencies=[Depends(require_role("admin"))]` | Task 2 Step 1 |
| 5 | `material.py` | same | Task 2 Step 2 |
| 6 | `price.py` | same | Task 2 Step 3 |
| 7 | `price_ingestion.py` | same (router had no prefix/args) | Task 2 Step 4 |
| 8 | `project.py` | `dependencies=[Depends(get_current_user)]` | Task 2 Step 7 |
| 9 | `allocation.py` | same | Task 2 Step 8 |
| 10 | `order.py` | same (router had no prefix) | Task 2 Step 9 |
| 11 | `purchase_record.py` | same | Task 2 Step 10 |

- [ ] **Step 6: Update `docs/data-model.md`**

Add a note in the `Project`/`Order`/`PurchaseRecord`/`AllocationLine` table descriptions documenting the new `created_by_user_id`/`overridden_by_user_id` columns and the removal of `Project.created_by` (String), referencing ADR-0024 §6, following the same style as the existing `User`/`UserSession` note added in part 1 (`docs/data-model.md:274-286`).

- [ ] **Step 7: Update `docs/architecture.md`**

Add a one-paragraph note that all 9 previously-open business routers are now behind `get_current_user`/`require_role("admin")` per ADR-0024 §4/§5, referencing the auth component already documented from part 1.

- [ ] **Step 8: Final commit**

```bash
git add docs/data-model.md docs/architecture.md
git commit -m "docs: reflect ADR-0024 §6 audit columns and full router protection in data-model/architecture"
```

---

## Self-Review Notes (for the plan author, not a task)

- **Spec coverage:** ADR-0024 §4 permission matrix — Task 2 (9 routers) + confirmation of `user.py`/`auth.py` (already done). §5 checklist — Task 6 Step 5 produces the literal reconciliation table the ADR itself calls for. §6 audit columns — Task 1 (schema/migration) + Task 3 (call sites). Test fixture requirement from ADR-0024 "Последствия" section — Tasks 4-5. Manual proof requested by the task instructions (not the ADR itself) — Task 6 Step 4.
- **Out of scope, confirmed:** frontend (§7), rate limiting (§10) — untouched, consistent with task instructions.
- **Type/name consistency check:** `override_allocation_line_supplier(..., overridden_by_user_id=None)` (Task 3 Step 3) is the exact name used by both call sites added in Task 3 Steps 4 and 6 — `replace_and_sync_order` forwards its own `overridden_by_user_id` parameter to the same-named kwarg, not a differently-named one. `create_orders_for_run(..., created_by_user_id=None)` (Task 3 Step 5) matches the kwarg used in Task 3 Step 7's `create_orders` endpoint. `create_purchase_record(..., created_by_user_id=None)` (Task 3 Step 8) matches Task 3 Step 9's call site.
