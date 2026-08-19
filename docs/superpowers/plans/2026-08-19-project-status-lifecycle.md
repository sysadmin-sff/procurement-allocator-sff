# Project Status Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Project.status` a real, honest lifecycle (`draft →
calculated → ordered → completed`) instead of a column that always reads
`"draft"`, wiring it into the existing allocation/order flow and backfilling
existing rows.

**Architecture:** `Project.status` transitions happen as a side effect of
existing service functions (`run_allocation()`, `create_orders_for_run()`)
rather than through a separate "set status" endpoint — the status must always
match what the data already says happened. The only user-driven transition is
`ordered → completed`, exposed as a new `POST /projects/{id}/complete`
endpoint. A one-time Alembic data migration backfills existing rows using the
same rule the service-layer code uses going forward, so there is exactly one
place that encodes "how do we know a project reached this stage."

**Tech Stack:** FastAPI, SQLAlchemy 2.0 ORM, Alembic, pytest (backend);
React + TypeScript, Vitest, react-router-dom (frontend).

**Spec:** `docs/decisions/0011-project-status-lifecycle.md`

## Global Constraints

- `Project.status` stays `String(20)`, no DB-level enum/CHECK constraint —
  values are fixed by convention in code and the ADR, not the schema (ADR-0011 §1).
- Only an `AllocationRun` with `status == "ok"` may ever move `Project.status`
  forward or backward between `draft`/`calculated`/`ordered` — `"infeasible"`
  runs must never change `Project.status` (ADR-0011 §2, §3).
- `completed` is terminal — no code path may transition a project out of
  `completed` (ADR-0011 §5).
- Backfill migration must use the exact same "has `Order`? has `ok`
  `AllocationRun`? else draft" rule as the runtime code (ADR-0011 §6) — do
  not hand-roll a second version of this rule.
- Money/quantity math stays backend-only (CLAUDE.md principle 4) — the
  frontend only ever displays `status` and `latest_allocation_run`, never
  computes or infers a status value itself.

---

## File Structure

**Backend — modified:**
- `backend/app/allocation/service.py` — `run_allocation()` sets
  `Project.status` after a solved run.
- `backend/app/allocation/order_service.py` — `create_orders_for_run()` sets
  `Project.status` to `"ordered"`.
- `backend/app/api/project.py` — new `POST /projects/{project_id}/complete`
  endpoint + `ProjectNotOrderedError`.

**Backend — new:**
- `backend/alembic/versions/<rev>_backfill_project_status.py` — data-only
  migration (no schema change).
- `backend/tests/allocation/test_project_status.py` — status-transition
  tests for `run_allocation()`/`create_orders_for_run()`.
- `backend/tests/project/test_complete.py` — tests for the new endpoint.

**Backend — modified tests:**
- `backend/tests/allocation/test_service.py` — existing `run_allocation()`
  tests keep passing; no new assertions required there (status is covered in
  the new file), but check nothing there hard-codes `project.status`.

**Frontend — modified:**
- `frontend/src/api/types.ts` — add `ProjectStatus` union, use it on
  `Project.status`.
- `frontend/src/api/projects.ts` — add `complete(id)`.
- `frontend/src/routes/ProjectRouterPage.tsx` — switch condition from
  `latest_allocation_run == null` to `project.status === 'draft'`.
- `frontend/src/routes/ProjectDetailPage.tsx` — add "Завершить проект"
  button, visible only when `status === 'ordered'`.
- `frontend/src/routes/ProjectRouterPage.tsx` test file if one exists (check
  in Task 8) and `ProjectDetailPage.test.tsx`, `ProjectsListPage.test.tsx`,
  `ProjectBuilderPage.test.tsx` — update fixtures that assumed the old
  routing condition.

**Docs — modified:**
- `docs/data-model.md` — document `Project.status` values/transitions.
- `docs/ui-reference.md` — new entry: where status shows, "Завершить
  проект" button condition.

---

### Task 1: `run_allocation()` sets `Project.status` on a solved run only

**Files:**
- Modify: `backend/app/allocation/service.py:80-181` (`run_allocation`)
- Test: `backend/tests/allocation/test_project_status.py` (new file)

**Interfaces:**
- Consumes: `app.models.Project`, existing `run_allocation(db: Session,
  project_id: uuid.UUID) -> AllocationRun` signature (unchanged).
- Produces: `run_allocation()` now also mutates and commits
  `Project.status` as a side effect. No new public function — later tasks
  import nothing new from this file.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/allocation/test_project_status.py`:

```python
import pytest

from app.allocation.service import run_allocation
from app.models import Project


def test_run_allocation_moves_draft_to_calculated_on_solved_run(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    assert project.status == "draft"

    run_allocation(session, project.id)

    session.refresh(project)
    assert project.status == "calculated"


def test_run_allocation_infeasible_run_does_not_move_draft_project(
    db_session, make_supplier, make_material, make_price, make_project
):
    """A supplier under its own per_order_min_amount for a single line makes
    the model infeasible (ADR-0002 Constraint 4 vs Constraint 1) — the
    project must stay draft, not silently advance. See ADR-0011 п.2."""
    session, *_ = db_session
    supplier = make_supplier(
        flat_fee=0.0, free_shipping_threshold=0.0, per_order_min_amount=1000.0
    )
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])  # 10 * 5.00 = 50.00, far under 1000.00

    run = run_allocation(session, project.id)

    assert run.status == "infeasible"
    session.refresh(project)
    assert project.status == "draft"


def test_run_allocation_infeasible_run_does_not_regress_calculated_project(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Starts from a project with one successful run (status=calculated),
    then expires its only workable price and replaces it with one that
    violates per_order_min_amount, forcing the second run to be infeasible
    (orphaned materials alone don't make a whole run infeasible — only a
    min-order violation or an empty solvable set does, see
    docs/decisions/0003-infeasible-allocation-status.md). The project must
    stay at "calculated", not regress to "draft"."""
    session, *_ = db_session
    ok_supplier = make_supplier(
        name="OK Supplier", flat_fee=0.0, free_shipping_threshold=0.0
    )
    material = make_material()
    make_price(material, ok_supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run_allocation(session, project.id)
    session.refresh(project)
    assert project.status == "calculated"

    # Expire the only workable price and replace it with one that violates
    # per_order_min_amount, so the next run is infeasible.
    import datetime

    from app.models import Price

    session.query(Price).filter(
        Price.material_id == material.id, Price.supplier_id == ok_supplier.id
    ).update({"valid_to": datetime.date.today()})
    session.flush()
    high_min_supplier = make_supplier(
        name="High Min Supplier",
        flat_fee=0.0,
        free_shipping_threshold=0.0,
        per_order_min_amount=1000.0,
    )
    make_price(material, high_min_supplier, price=5.00, availability=10)

    run = run_allocation(session, project.id)

    assert run.status == "infeasible"
    session.refresh(project)
    assert project.status == "calculated"  # unchanged, not regressed to draft
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/allocation/test_project_status.py -v`
Expected: FAIL — `project.status` stays `"draft"` after a solved run (no
code sets it yet).

- [ ] **Step 3: Implement the status transition in `run_allocation()`**

In `backend/app/allocation/service.py`, add `Project` to the existing
import line:

```python
from app.models import AllocationLine, AllocationRun, Price, Project, ProjectItem, Supplier
```

Then find the tail of `run_allocation()`:

```python
    run = AllocationRun(
        project_id=project_id,
        algorithm_version=ALGORITHM_VERSION,
        status="ok" if solved else "infeasible",
        orphaned_materials=[asdict(o) for o in orphaned],
        supplier_summaries=supplier_summaries,
    )
    db.add(run)
    db.flush()

    if solved:
        for line in result.lines:
            db.add(
                AllocationLine(
                    allocation_run_id=run.id,
                    material_id=uuid.UUID(line.material_id),
                    supplier_id=uuid.UUID(line.supplier_id),
                    quantity=line.quantity,
                    unit_price=_from_cents(line.unit_price_cents),
                    line_total=_from_cents(line.line_total_cents),
                )
            )

    db.commit()
    db.refresh(run)
    return run
```

Replace it with (adds the status transition as the first statement inside
the existing `if solved:` block, before the `AllocationLine` loop):

```python
    run = AllocationRun(
        project_id=project_id,
        algorithm_version=ALGORITHM_VERSION,
        status="ok" if solved else "infeasible",
        orphaned_materials=[asdict(o) for o in orphaned],
        supplier_summaries=supplier_summaries,
    )
    db.add(run)
    db.flush()

    if solved:
        project = db.get(Project, project_id)
        if project.status in ("draft", "ordered"):
            project.status = "calculated"

        for line in result.lines:
            db.add(
                AllocationLine(
                    allocation_run_id=run.id,
                    material_id=uuid.UUID(line.material_id),
                    supplier_id=uuid.UUID(line.supplier_id),
                    quantity=line.quantity,
                    unit_price=_from_cents(line.unit_price_cents),
                    line_total=_from_cents(line.line_total_cents),
                )
            )

    db.commit()
    db.refresh(run)
    return run
```

`if project.status in ("draft", "ordered")` leaves `calculated` untouched
on a second `"ok"` run (already the target value) and excludes `completed`
entirely — a terminal status per ADR-0011 §5 must never be moved by this
function.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/allocation/test_project_status.py -v`
Expected: PASS (all three tests)

- [ ] **Step 5: Run the full allocation test suite to check for regressions**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/allocation/ -v`
Expected: PASS (all existing tests still pass — none of them assert
`project.status`, so none should break)

- [ ] **Step 6: Commit**

```bash
git add backend/app/allocation/service.py backend/tests/allocation/test_project_status.py
git commit -m "feat: run_allocation moves Project.status draft/ordered -> calculated on a solved run (ADR-0011)"
```

---

### Task 2: `create_orders_for_run()` sets `Project.status` to `"ordered"`

**Files:**
- Modify: `backend/app/allocation/order_service.py:45-99` (`create_orders_for_run`)
- Test: `backend/tests/allocation/test_project_status.py` (append)

**Interfaces:**
- Consumes: `app.models.Project`; existing `create_orders_for_run(db:
  Session, project_id: uuid.UUID, run_id: uuid.UUID) -> list[Order]`
  signature (unchanged).
- Produces: side effect on `Project.status`, no new public symbol.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/allocation/test_project_status.py`:

```python
from app.allocation.order_service import create_orders_for_run


def test_create_orders_moves_calculated_to_ordered(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    run = run_allocation(session, project.id)
    session.refresh(project)
    assert project.status == "calculated"

    create_orders_for_run(session, project.id, run.id)

    session.refresh(project)
    assert project.status == "ordered"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/allocation/test_project_status.py::test_create_orders_moves_calculated_to_ordered -v`
Expected: FAIL — `project.status` stays `"calculated"`.

- [ ] **Step 3: Implement the status transition in `create_orders_for_run()`**

In `backend/app/allocation/order_service.py`, the function currently ends
with:

```python
        orders.append(order)

    db.commit()
    for order in orders:
        db.refresh(order)
    return orders
```

Change to set the project status before the commit, but only if at least
one `Order` was actually created (an empty `supplier_summaries` — e.g. an
infeasible run somehow reused here, or a run with zero suppliers — must not
silently flip status with nothing to back it):

```python
        orders.append(order)

    if orders:
        project = db.get(Project, project_id)
        project.status = "ordered"

    db.commit()
    for order in orders:
        db.refresh(order)
    return orders
```

Add `Project` to the existing import line:

```python
from app.models import AllocationLine, AllocationRun, Order, OrderItem, Project
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/allocation/test_project_status.py -v`
Expected: PASS (all four tests so far)

- [ ] **Step 5: Run the full allocation test suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/allocation/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/allocation/order_service.py backend/tests/allocation/test_project_status.py
git commit -m "feat: create_orders_for_run moves Project.status to ordered (ADR-0011)"
```

---

### Task 3: Regression — re-running allocation on an `ordered` project rolls back to `calculated`

This is already covered mechanically by Task 1's `if project.status in
("draft", "ordered")` condition, but needs its own explicit test tying the
two service functions together end-to-end, since Task 1 and Task 2 only
tested each function in isolation.

**Files:**
- Test: `backend/tests/allocation/test_project_status.py` (append)

**Interfaces:**
- Consumes: `run_allocation`, `create_orders_for_run` (both already
  imported by prior tasks in this file).
- Produces: nothing new — verification-only task.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/allocation/test_project_status.py`:

```python
def test_recalculating_ordered_project_rolls_back_to_calculated(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])

    first_run = run_allocation(session, project.id)
    create_orders_for_run(session, project.id, first_run.id)
    session.refresh(project)
    assert project.status == "ordered"

    run_allocation(session, project.id)

    session.refresh(project)
    assert project.status == "calculated"
```

- [ ] **Step 2: Run test**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/allocation/test_project_status.py::test_recalculating_ordered_project_rolls_back_to_calculated -v`
Expected: PASS immediately (Task 1's implementation already covers this —
this step is confirmation, not new code)

If it fails, the bug is in Task 1's condition — fix
`backend/app/allocation/service.py` so `"ordered"` is included in the set of
statuses that move to `"calculated"` on a solved run, then re-run.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/allocation/test_project_status.py
git commit -m "test: cover ordered -> calculated regression on recalculation (ADR-0011 §3)"
```

---

### Task 4: `POST /projects/{project_id}/complete` endpoint

**Files:**
- Modify: `backend/app/api/project.py`
- Modify: `backend/tests/project/conftest.py` (already exists — extend it,
  do not replace it; see Step 1)
- Test: `backend/tests/project/test_complete.py` (new file)

**Interfaces:**
- Consumes: `app.models.Project`.
- Produces: `POST /projects/{project_id}/complete` route returning
  `ProjectOut`. No new exception class — the status check is a single
  condition inline in the route (unlike `delete_project`'s cascade logic,
  there's no separate service function here worth splitting out, so this
  follows the same file's simpler routes like `update_project` instead of
  the `ProjectHasSentOrdersError` pattern).

- [ ] **Step 1: Extend the existing `make_project` fixture with an optional `status` param**

`backend/tests/project/conftest.py` already exists (used by
`backend/tests/project/test_api.py`) with this `make_project` fixture:

```python
@pytest.fixture
def make_project(db_session):
    session, project_ids, _material_ids = db_session

    def _make(title="Test Project", created_by=None):
        project = Project(title=title, created_by=created_by)
        session.add(project)
        session.flush()
        project_ids.append(project.id)
        return project

    return _make
```

Note `db_session` here unpacks as a 3-tuple (`session, project_ids,
material_ids` — no `supplier_ids`), different from
`backend/tests/allocation/conftest.py`'s 4-tuple. Do not copy the
allocation conftest's fixtures wholesale; extend this file's existing
`make_project` in place by adding a `status` parameter, keeping every
existing call site (which only ever passes `title`/`created_by`) working
unchanged:

```python
@pytest.fixture
def make_project(db_session):
    session, project_ids, _material_ids = db_session

    def _make(title="Test Project", created_by=None, status="draft"):
        project = Project(title=title, created_by=created_by, status=status)
        session.add(project)
        session.flush()
        project_ids.append(project.id)
        return project

    return _make
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/project/test_complete.py`:

```python
import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_complete_ordered_project_returns_200(db_session, make_project):
    project = make_project(status="ordered")

    response = client.post(f"/projects/{project.id}/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_complete_draft_project_returns_409(db_session, make_project):
    project = make_project(status="draft")

    response = client.post(f"/projects/{project.id}/complete")

    assert response.status_code == 409


def test_complete_calculated_project_returns_409(db_session, make_project):
    project = make_project(status="calculated")

    response = client.post(f"/projects/{project.id}/complete")

    assert response.status_code == 409


def test_complete_already_completed_project_returns_409(db_session, make_project):
    project = make_project(status="completed")

    response = client.post(f"/projects/{project.id}/complete")

    assert response.status_code == 409


def test_complete_unknown_project_returns_404():
    response = client.post(f"/projects/{uuid.uuid4()}/complete")

    assert response.status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/project/test_complete.py -v`
Expected: FAIL with 404s (route doesn't exist yet) on every test

- [ ] **Step 4: Implement the endpoint**

In `backend/app/api/project.py`, add after `update_project` and before
`get_project` (or anywhere among the other `/{project_id}` routes — exact
position doesn't matter, FastAPI matches by path+method):

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/project/test_complete.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -v`
Expected: PASS (no regressions)

- [ ] **Step 7: Run ruff**

Run: `cd backend && .venv/Scripts/python.exe -m ruff check .`
Expected: All checks passed!

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/project.py backend/tests/project/
git commit -m "feat: POST /projects/{id}/complete endpoint, ordered -> completed only (ADR-0011 §4)"
```

---

### Task 5: Backfill migration for existing `Project` rows

**Files:**
- Create: `backend/alembic/versions/<rev>_backfill_project_status.py`
  (generate the revision id per Step 1 below)
- Modify: `backend/tests/project/conftest.py` (extend further — see Step 3;
  builds on Task 4's Step 1 change to the same file)
- Test: `backend/tests/project/test_status_backfill.py` (new file)

**Interfaces:**
- Consumes: existing `projects`, `allocation_runs`, `orders` tables (raw SQL
  in the migration — Alembic data migrations don't import ORM models, per
  the pattern of every other migration in `backend/alembic/versions/`).
- Produces: nothing new for other tasks — this is a standalone data
  migration plus its own test that runs the same logic directly against a
  throwaway set of rows to verify the SQL is correct, since running a real
  Alembic upgrade/downgrade cycle inside pytest is out of scope for this
  codebase's existing test patterns (none of the current tests do that).

- [ ] **Step 1: Find the current Alembic head and generate a revision id**

Run: `cd backend && .venv/Scripts/python.exe -m alembic heads`
Expected output: `4f2931515181 (head)`

Generate a new 12-hex-char revision id fragment for the filename:
Run: `cd backend && .venv/Scripts/python.exe -c "import uuid; print(uuid.uuid4().hex[:12])"`

Use that value as both the filename prefix and the `revision` field below
(this plan uses `a1b2c3d4e5f6` as a placeholder — replace it with your
generated value everywhere it appears in this task).

- [ ] **Step 2: Write the migration**

Create `backend/alembic/versions/a1b2c3d4e5f6_backfill_project_status.py`:

```python
"""backfill Project.status from existing AllocationRun/Order data (ADR-0011)

Revision ID: a1b2c3d4e5f6
Revises: 4f2931515181
Create Date: 2026-08-19 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "4f2931515181"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rule must match app.allocation.service.run_allocation() /
    # app.allocation.order_service.create_orders_for_run() exactly (ADR-0011 §6):
    # has an Order -> "ordered"; else has an AllocationRun with status="ok" ->
    # "calculated"; else leave as "draft" (already the default, untouched).
    op.execute(
        """
        UPDATE projects
        SET status = 'calculated'
        WHERE status = 'draft'
          AND EXISTS (
              SELECT 1 FROM allocation_runs
              WHERE allocation_runs.project_id = projects.id
                AND allocation_runs.status = 'ok'
          )
        """
    )
    op.execute(
        """
        UPDATE projects
        SET status = 'ordered'
        WHERE EXISTS (
            SELECT 1 FROM orders
            WHERE orders.project_id = projects.id
        )
        """
    )


def downgrade() -> None:
    # Data migration — no reliable inverse (we can't tell which projects were
    # genuinely "draft" before vs. backfilled). Left as a no-op, matching how
    # data-only corrections in this project are not designed to be reversible
    # (there is no prior precedent for a data-migration downgrade in
    # backend/alembic/versions/ to follow instead).
    pass
```

Note the two-step order: the first `UPDATE` only touches rows still at
`'draft'` (so it can never stomp a row that's already `'ordered'` from a
previous run of this migration, though it only runs once); the second
`UPDATE` has no `WHERE status = ...` guard because "has an Order" always
wins regardless of what the first step set it to — a project can have both
an `'ok'` `AllocationRun` and an `Order`, and it must end at `'ordered'`,
not `'calculated'`.

- [ ] **Step 3: Write a test that exercises the same SQL against real rows**

Create `backend/tests/project/test_status_backfill.py`:

```python
"""Verifies the backfill SQL in the ADR-0011 migration
(a1b2c3d4e5f6_backfill_project_status.py) against representative rows,
including the dev-DB case documented in the ADR: a project with both
infeasible and ok AllocationRuns plus an Order, which must land on
"ordered" — not be miscategorized by the infeasible runs alone.
"""

from sqlalchemy import text


def _run_backfill(session):
    session.execute(
        text(
            """
            UPDATE projects
            SET status = 'calculated'
            WHERE status = 'draft'
              AND EXISTS (
                  SELECT 1 FROM allocation_runs
                  WHERE allocation_runs.project_id = projects.id
                    AND allocation_runs.status = 'ok'
              )
            """
        )
    )
    session.execute(
        text(
            """
            UPDATE projects
            SET status = 'ordered'
            WHERE EXISTS (
                SELECT 1 FROM orders
                WHERE orders.project_id = projects.id
            )
            """
        )
    )
    session.flush()


def test_backfill_leaves_project_with_no_runs_as_draft(db_session, make_project):
    session, *_ = db_session
    project = make_project(status="draft")

    _run_backfill(session)

    session.refresh(project)
    assert project.status == "draft"


def test_backfill_leaves_project_with_only_infeasible_runs_as_draft(
    db_session, make_project
):
    session, *_ = db_session
    from app.models import AllocationRun

    project = make_project(status="draft")
    session.add(
        AllocationRun(
            project_id=project.id,
            algorithm_version="test",
            status="infeasible",
            orphaned_materials=[],
            supplier_summaries=[],
        )
    )
    session.flush()

    _run_backfill(session)

    session.refresh(project)
    assert project.status == "draft"


def test_backfill_sets_calculated_for_project_with_ok_run_only(
    db_session, make_project
):
    session, *_ = db_session
    from app.models import AllocationRun

    project = make_project(status="draft")
    session.add(
        AllocationRun(
            project_id=project.id,
            algorithm_version="test",
            status="ok",
            orphaned_materials=[],
            supplier_summaries=[],
        )
    )
    session.flush()

    _run_backfill(session)

    session.refresh(project)
    assert project.status == "calculated"


def test_backfill_sets_ordered_for_project_with_infeasible_ok_and_order(
    db_session, make_project, make_supplier
):
    """Mirrors the real dev-DB project documented in ADR-0011 §6:
    5 infeasible runs, 26 ok runs, 3 orders -> must land on "ordered"."""
    session, *_ = db_session
    from app.models import AllocationRun, Order

    project = make_project(status="draft")
    supplier = make_supplier()
    for _ in range(5):
        session.add(
            AllocationRun(
                project_id=project.id,
                algorithm_version="test",
                status="infeasible",
                orphaned_materials=[],
                supplier_summaries=[],
            )
        )
    for _ in range(26):
        session.add(
            AllocationRun(
                project_id=project.id,
                algorithm_version="test",
                status="ok",
                orphaned_materials=[],
                supplier_summaries=[],
            )
        )
    for _ in range(3):
        session.add(
            Order(
                project_id=project.id,
                supplier_id=supplier.id,
                status="draft",
                total_amount=100.0,
                delivery_fee=0.0,
            )
        )
    session.flush()

    _run_backfill(session)

    session.refresh(project)
    assert project.status == "ordered"
```

This test file needs a `make_supplier` fixture, which `backend/tests/project/conftest.py`
does not have yet (it only has `db_session`, `make_project`, `make_material`
— see Task 4 Step 1). Extend `backend/tests/project/conftest.py` again:

Add `Supplier` to its existing import line (`from app.models import
Material, Project, ProjectItem` becomes):

```python
from app.models import Material, Project, ProjectItem, Supplier
```

Add a `supplier_ids` list to the existing `db_session` fixture and clean it
up alongside the existing cleanup, and yield it as a fourth tuple element.
The existing fixture is:

```python
@pytest.fixture
def db_session():
    session = SessionLocal()
    project_ids: list = []
    material_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, project_ids, material_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
        if project_ids:
            session.query(ProjectItem).filter(
                ProjectItem.project_id.in_(project_ids)
            ).delete(synchronize_session=False)
            session.query(Project).filter(Project.id.in_(project_ids)).delete(
                synchronize_session=False
            )
        if material_ids:
            session.query(Material).filter(Material.id.in_(material_ids)).delete(
                synchronize_session=False
            )
        session.commit()
        session.close()
```

Replace it with (adds `supplier_ids`, cleaned up after `project_ids` so
that `Order` rows referencing a supplier are already gone by the time the
supplier itself is deleted — `Order` deletion isn't needed here since these
tests only ever create `AllocationRun`/`Order` rows directly against
`Project`, which the existing `project_ids` cleanup doesn't touch; add that
cleanup too, since Task 5's tests create `AllocationRun` and `Order` rows
that the current fixture has no cleanup path for at all):

```python
@pytest.fixture
def db_session():
    session = SessionLocal()
    project_ids: list = []
    material_ids: list = []
    supplier_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, project_ids, material_ids, supplier_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
        for project_id in project_ids:
            order_ids = [
                o.id for o in session.query(Order).filter_by(project_id=project_id).all()
            ]
            if order_ids:
                session.query(Order).filter(Order.id.in_(order_ids)).delete(
                    synchronize_session=False
                )
            run_ids = [
                r.id
                for r in session.query(AllocationRun).filter_by(project_id=project_id).all()
            ]
            if run_ids:
                session.query(AllocationRun).filter(AllocationRun.id.in_(run_ids)).delete(
                    synchronize_session=False
                )
        if project_ids:
            session.query(ProjectItem).filter(
                ProjectItem.project_id.in_(project_ids)
            ).delete(synchronize_session=False)
            session.query(Project).filter(Project.id.in_(project_ids)).delete(
                synchronize_session=False
            )
        if material_ids:
            session.query(Material).filter(Material.id.in_(material_ids)).delete(
                synchronize_session=False
            )
        if supplier_ids:
            session.query(Supplier).filter(Supplier.id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
        session.commit()
        session.close()
```

Add `AllocationRun` and `Order` to the import line too:

```python
from app.models import AllocationRun, Material, Order, Project, ProjectItem, Supplier
```

This changes `db_session`'s yielded tuple from 3 to 4 elements
(`session, project_ids, material_ids, supplier_ids`). Two existing tests in
`backend/tests/project/test_api.py` unpack it explicitly with the old
3-name form and will raise `ValueError: too many values to unpack` once
this fixture yields 4 — fix both:

`test_create_project_returns_201_with_body` (currently `session,
project_ids, _material_ids = db_session`):

```python
def test_create_project_returns_201_with_body(db_session):
    session, project_ids, _material_ids, _supplier_ids = db_session
```

`test_get_project_returns_created_project_with_items` (currently `session,
_project_ids, _material_ids = db_session`):

```python
def test_get_project_returns_created_project_with_items(db_session, make_project, make_material):
    session, _project_ids, _material_ids, _supplier_ids = db_session
```

`backend/tests/project/test_complete.py` (Task 4) only ever uses
`db_session` as a fixture dependency to trigger cleanup, never unpacks it
(see its test bodies in Task 4 Step 2 — none of them destructure
`db_session`), so it needs no change here.

Update `make_project` and `make_material` (both already unpack
`db_session` positionally) to match the new 4-tuple — only the first line
of each function body changes, everything else stays exactly as it already
is in the file:

```python
@pytest.fixture
def make_project(db_session):
    session, project_ids, _material_ids, _supplier_ids = db_session

    def _make(title="Test Project", created_by=None, status="draft"):
        project = Project(title=title, created_by=created_by, status=status)
        session.add(project)
        session.flush()
        project_ids.append(project.id)
        return project

    return _make


@pytest.fixture
def make_material(db_session):
    session, _project_ids, material_ids, _supplier_ids = db_session

    def _make(sku=None, canonical_name=None, category=None, unit="ft"):
        sku = sku or f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        material = Material(
            internal_sku=sku, canonical_name=canonical_name or sku, category=category, unit=unit
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make
```

Finally add `make_supplier`:

```python
@pytest.fixture
def make_supplier(db_session):
    session, _project_ids, _material_ids, supplier_ids = db_session

    def _make(name="Test Supplier"):
        supplier = Supplier(name=name, currency="USD", delivery_policy={})
        session.add(supplier)
        session.flush()
        supplier_ids.append(supplier.id)
        return supplier

    return _make
```

- [ ] **Step 4: Run `test_api.py` and `test_complete.py` to confirm the conftest changes didn't break them**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/project/ -v`
Expected: PASS for every test in `tests/project/test_api.py` and
`tests/project/test_complete.py` (Task 4) — this confirms the `db_session`
4-tuple change and the two explicit-unpack fixes above are correct before
adding the new backfill test file.

- [ ] **Step 5: Run the new backfill test to verify it passes**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/project/test_status_backfill.py -v`
Expected: PASS — this task's "test" is verifying the SQL directly (there's
no separate "before" implementation state to fail against, since the SQL
lives inline in the test helper). If any test fails, the SQL in
`_run_backfill` has a bug — fix it and the migration file identically.

- [ ] **Step 6: Apply the migration to the dev database**

Run: `cd backend && .venv/Scripts/python.exe -m alembic upgrade head`
Expected: `Running upgrade 4f2931515181 -> a1b2c3d4e5f6, backfill Project.status...`

- [ ] **Step 7: Verify against the real dev-DB project from the ADR**

Run:
```bash
cd backend && .venv/Scripts/python.exe -c "
from app.core.database import SessionLocal
from app.models import Project
s = SessionLocal()
p = s.get(Project, '8837ffb9-1145-4472-bb69-a1b17aac2606')
print('status:', p.status)
s.close()
"
```
Expected: `status: ordered` (this project has 3 Orders per the ADR — confirmed
during brainstorming)

- [ ] **Step 8: Run the full backend test suite and ruff**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -v && .venv/Scripts/python.exe -m ruff check .`
Expected: all PASS, no ruff errors

- [ ] **Step 9: Commit**

```bash
git add backend/alembic/versions/a1b2c3d4e5f6_backfill_project_status.py backend/tests/project/
git commit -m "feat: backfill Project.status for existing rows (ADR-0011 §6)"
```

---

### Task 6: Frontend types and API client

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/projects.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ProjectStatus` type exported from `types.ts`; `Project.status:
  ProjectStatus` (was `string`); `projectsApi.complete(id: string):
  Promise<Project>`.

- [ ] **Step 1: Add the `ProjectStatus` type and use it on `Project`**

In `frontend/src/api/types.ts`, find:

```typescript
export interface Project {
  id: string;
  title: string;
  created_by: string | null;
  status: string;
  created_at: string;
}
```

Replace with:

```typescript
export type ProjectStatus = 'draft' | 'calculated' | 'ordered' | 'completed';

export interface Project {
  id: string;
  title: string;
  created_by: string | null;
  status: ProjectStatus;
  created_at: string;
}
```

- [ ] **Step 2: Add `complete()` to the API client**

In `frontend/src/api/projects.ts`, add after `remove`:

```typescript
export const projectsApi = {
  list: () => http.get<Project[]>('/projects'),
  create: (payload: ProjectCreate) => http.post<Project>('/projects', payload),
  updateProject: (id: string, title: string) => http.patch<Project>(`/projects/${id}`, { title }),
  get: (id: string) => http.get<ProjectWithItems>(`/projects/${id}`),
  addItem: (projectId: string, payload: ProjectItemCreate) =>
    http.post<ProjectItem>(`/projects/${projectId}/items`, payload),
  updateItem: (projectId: string, itemId: string, quantity: number) =>
    http.patch<ProjectItem>(`/projects/${projectId}/items/${itemId}`, { quantity }),
  removeItem: (projectId: string, itemId: string) =>
    http.delete<void>(`/projects/${projectId}/items/${itemId}`),
  remove: (id: string) => http.delete<void>(`/projects/${id}`),
  complete: (id: string) => http.post<Project>(`/projects/${id}/complete`, {}),
};
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc -b`
Expected: errors in files that build a `Project`/`ProjectWithItems` object
literal with a `status` value TypeScript can't narrow to `ProjectStatus`
(e.g. test fixtures using `status: 'draft'` as a plain string in a context
expecting the literal union — most `'draft'`/`'ok'` string literals infer
fine, but check the compiler output for exact failures before proceeding to
Task 8, which fixes any remaining test fixtures)

Do not fix test fixtures yet — that's Task 8. This step is only to confirm
`ProjectStatus` compiles cleanly in `types.ts`/`projects.ts` themselves;
transitively-broken test files are expected and handled later.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/projects.ts
git commit -m "feat: add ProjectStatus type and projectsApi.complete() (ADR-0011)"
```

---

### Task 7: `ProjectRouterPage` switches on `status`, `ProjectDetailPage` gets the "Завершить проект" button

**Files:**
- Modify: `frontend/src/routes/ProjectRouterPage.tsx`
- Modify: `frontend/src/routes/ProjectDetailPage.tsx`

**Interfaces:**
- Consumes: `project.status` (from Task 6's `ProjectStatus` type),
  `projectsApi.complete` (from Task 6).
- Produces: nothing new for later tasks — this is the last functional
  change; Task 8 only fixes tests.

- [ ] **Step 1: Switch `ProjectRouterPage.tsx`'s routing condition**

In `frontend/src/routes/ProjectRouterPage.tsx`, find:

```typescript
  if (project.latest_allocation_run == null) {
    return <ProjectBuilderPage projectId={projectId} initialProject={project} />;
  }

  return <ProjectDetailPage initialProject={project} />;
```

Replace with:

```typescript
  if (project.status === 'draft') {
    return <ProjectBuilderPage projectId={projectId} initialProject={project} />;
  }

  return <ProjectDetailPage initialProject={project} />;
```

Also update the doc comment above `ProjectRouterPage` (currently says
"depending on whether the project has ever been calculated... a project
with no `latest_allocation_run` is still a draft") to reflect the new
condition:

```typescript
/**
 * `/projects/:projectId` renders one of two screens depending on
 * `project.status` (see ADR-0011): `status === 'draft'` means the project
 * is still being assembled and has never had a solved AllocationRun — it
 * gets the keyboard-first builder grid (autosaving). Any later status
 * (`calculated`/`ordered`/`completed`) gets the read/edit detail screen
 * with the run summary.
 */
```

- [ ] **Step 2: Add the "Завершить проект" button to `ProjectDetailPage.tsx`**

In `frontend/src/routes/ProjectDetailPage.tsx`, the header currently reads:

```tsx
        <div className={styles.header}>
          <h1 className={styles.title}>{project?.title ?? 'Проект'}</h1>
          {status === 'ready' && project && (
            <Button
              variant="primary"
              onClick={() => navigate(`/projects/${projectId}/allocation`)}
            >
              {project.latest_allocation_run ? 'Пересчитать закупку »' : 'Рассчитать закупку »'}
            </Button>
          )}
        </div>
```

Replace with (adds a second button, conditional on `status === 'ordered'`,
next to the existing recalculate button):

```tsx
        <div className={styles.header}>
          <h1 className={styles.title}>{project?.title ?? 'Проект'}</h1>
          {status === 'ready' && project && (
            <div className={styles.actionsCell}>
              {project.status === 'ordered' && (
                <Button variant="secondary" onClick={() => void handleComplete()}>
                  Завершить проект
                </Button>
              )}
              <Button
                variant="primary"
                onClick={() => navigate(`/projects/${projectId}/allocation`)}
              >
                {project.latest_allocation_run ? 'Пересчитать закупку »' : 'Рассчитать закупку »'}
              </Button>
            </div>
          )}
        </div>
```

Add the `handleComplete` function next to the other handlers (e.g. right
after `handleAddItem`):

```typescript
  async function handleComplete() {
    if (!projectId) return;
    setActionError(null);
    try {
      const updated = await projectsApi.complete(projectId);
      setProject((prev) => (prev ? { ...prev, status: updated.status } : prev));
    } catch (err) {
      setActionError(err);
    }
  }
```

- [ ] **Step 3: Type-check and lint**

Run: `cd frontend && npx tsc -b`
Expected: same pre-existing test-fixture errors as Task 6 Step 3 (not new
ones from this step's files) — `ProjectDetailPage.tsx` itself should
compile cleanly since `project.status` is already typed and
`projectsApi.complete` exists from Task 6.

Run: `cd frontend && npm run lint`
Expected: only the pre-existing `DeliveryPolicyFields.tsx` warnings (from
earlier ADR-0010 frontend work), no new errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/ProjectRouterPage.tsx frontend/src/routes/ProjectDetailPage.tsx
git commit -m "feat: route by Project.status, add complete-project button (ADR-0011 §4, §7)"
```

---

### Task 8: Fix existing frontend tests broken by the `ProjectStatus` type and routing change

**Files:**
- Modify: `frontend/src/routes/ProjectDetailPage.test.tsx`
- Modify: `frontend/src/routes/ProjectsListPage.test.tsx`
- Modify: `frontend/src/routes/ProjectBuilderPage.test.tsx`
- Modify: `frontend/src/routes/AllocationResultPage.test.tsx`
- Modify: `frontend/src/routes/OrderDetailPage.test.tsx`
- Modify: `frontend/src/routes/OrderPrintPage.test.tsx`
- Check: any test file that renders `ProjectRouterPage` or asserts on
  `latest_allocation_run` driving which screen shows

**Interfaces:**
- Consumes: `ProjectStatus` (Task 6).
- Produces: nothing — this task only makes the existing suite green again.

- [ ] **Step 1: Run the full frontend test suite to see what's currently broken**

Run: `cd frontend && npm run test 2>&1 | tail -100`
Expected: failures listing which test files construct a `Project`/
`ProjectWithItems` object whose `status` field is a plain string that
doesn't satisfy `ProjectStatus`, and/or whose expected screen (builder vs.
detail) was keyed off `latest_allocation_run` instead of `status`.

- [ ] **Step 2: For each failing fixture, align `status` with the actual scenario**

Every existing fixture in these files already sets `status: 'draft'` (see
the earlier `grep` in this plan's research — all current test fixtures use
`'draft'` regardless of scenario, e.g. a test that sets
`latest_allocation_run: { ... }` to force the detail screen while `status`
stays `'draft'`). For any test whose fixture is meant to represent an
already-calculated project (check for `latest_allocation_run` set to a
non-null value, or the test asserting the detail screen renders), change
`status: 'draft'` to `status: 'calculated'` so the new routing condition in
Task 7 renders the same screen the test still expects.

Concretely, in `ProjectDetailPage.test.tsx`, `ProjectBuilderPage.test.tsx`
and any others: search each file for `status: 'draft'` and check the
surrounding fixture — if it also sets a non-null `latest_allocation_run`
(meaning the test's intent is "a project that's already been calculated"),
change that fixture's `status` to `'calculated'`. Leave fixtures with
`latest_allocation_run: null` as `status: 'draft'` — those are genuinely
testing the draft/builder path and should stay consistent.

- [ ] **Step 3: Re-run the frontend test suite**

Run: `cd frontend && npm run test 2>&1 | tail -100`
Expected: all PASS

- [ ] **Step 4: Run the full type-check**

Run: `cd frontend && npx tsc -b`
Expected: no errors

- [ ] **Step 5: Run the full build**

Run: `cd frontend && npm run build`
Expected: succeeds

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/*.test.tsx
git commit -m "test: align Project.status fixtures with new draft/calculated routing (ADR-0011)"
```

---

### Task 9: Docs

**Files:**
- Modify: `docs/data-model.md`
- Modify: `docs/ui-reference.md`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing — documentation only, no code depends on this task.

- [ ] **Step 1: Document `Project.status` in `docs/data-model.md`**

Find the `Project` entity block in the Mermaid diagram:

```
    Project {
        uuid id
        string title
        string status
    }
```

Replace with:

```
    Project {
        uuid id
        string title
        string status "draft/calculated/ordered/completed, см. ADR-0011"
    }
```

After the existing prose paragraph about `PurchaseRecord` (the last
paragraph in the file), add a new paragraph:

```markdown
`Project.status` — добавлено сверх исходной диаграммы, см.
`docs/decisions/0011-project-status-lifecycle.md`. `draft → calculated →
ordered → completed`. Первые три перехода — автоматические, побочный
эффект `run_allocation()`/`create_orders_for_run()` (по наличию
`AllocationRun.status == "ok"` / `Order` для проекта, не по отдельному
действию пользователя). Только `AllocationRun` со статусом `"ok"` двигает
статус — `"infeasible"` не меняет его никогда, даже если это единственный
прогон у проекта. Повторный успешный расчёт на уже `ordered` проекте
откатывает статус в `calculated`. `ordered → completed` — единственный
ручной переход (кнопка «Завершить проект»), `completed` финален, без
обратного перехода.
```

- [ ] **Step 2: Document the button behavior in `docs/ui-reference.md`**

Add a new section, numbered after the existing highest section (currently
`## 5. Фактическая закупка`):

```markdown
## 6. Статус проекта на `ProjectDetailPage.tsx` / `ProjectRouterPage.tsx`

- `status === 'draft'` — показывается конструктор (`ProjectBuilderPage`),
  не детальный экран. Переключение целиком по `status`, не по наличию
  `latest_allocation_run` — см. ADR-0011 §7.
- Кнопка «Завершить проект» на `ProjectDetailPage` видна только при
  `status === 'ordered'`. После нажатия `status` становится `completed`
  без возможности вернуться назад — ни повторный расчёт, ни новый ордер
  этого не меняют. См. ADR-0011 §4–5.
- Расчёт со статусом `AllocationRun.status === 'infeasible'` (не
  `Project.status` — разные поля) никогда не двигает `Project.status`, в
  том числе при первом расчёте черновика — черновик остаётся `draft`,
  пока не будет хотя бы одного успешного (`"ok"`) расчёта. См.
  ADR-0011 §2.
```

- [ ] **Step 3: Commit**

```bash
git add docs/data-model.md docs/ui-reference.md
git commit -m "docs: document Project.status lifecycle (ADR-0011)"
```

---

### Task 10: Manual verification

**Files:** none — verification only.

- [ ] **Step 1: Start the backend**

Run (background): `cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`

- [ ] **Step 2: Start the frontend**

Run (background): `cd frontend && npm run dev`

- [ ] **Step 3: Walk through the lifecycle in the browser**

1. Create a new project, add at least one material with a valid price
   from some supplier — confirm it opens the builder screen (status
   `draft`).
2. Trigger a calculation (this navigates to the allocation screen) —
   go back to `/projects/:id` and confirm it now shows the detail screen
   (status `calculated`), and the list at `/projects` shows `calculated`
   in the Статус column.
3. Create orders from the allocation result — return to
   `/projects/:id`, confirm status shows `ordered` and the «Завершить
   проект» button is now visible.
4. Click «Завершить проект» — confirm status becomes `completed` and the
   button disappears.
5. Separately, create a second project with a material priced only from
   a supplier whose `per_order_min_amount` is far above the line total, run
   allocation, and confirm: the run shows as infeasible in the UI, and the
   project stays on the builder screen (status still `draft`), not the
   detail screen.

- [ ] **Step 4: Report findings**

Summarize what was verified and any deviations from expected behavior.
