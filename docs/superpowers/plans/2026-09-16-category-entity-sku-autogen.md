# Category Entity + SKU Autogeneration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `Material.category` (free-text `String`) with a managed
`Category` entity (`id`, `name`, `sku_prefix`, `requires_single_supplier`,
`next_sku_number`), autogenerate `internal_sku` atomically on material
creation, and make `solver.py`/`service.py` read strictness from
`Category.requires_single_supplier` instead of the hardcoded
`STRICT_CATEGORIES` constant.

**Architecture:** Two-phase Alembic migration (nullable FK, backfill,
NOT NULL + drop old column). A dry-run/`--apply` backfill script
(`backfill_material_categories.py`) creates the 8 `Category` rows from
`SELECT DISTINCT category` + `CATEGORY_SKU_PREFIX`, sets
`requires_single_supplier` from a script-local constant, and sets
`next_sku_number` from the max existing SKU suffix per prefix. `solver.py`
groups by `category_id`/`requires_single_supplier` instead of a
name-membership set; `service.py::_compute_split_categories` joins
`Category` instead of importing the old constant. `internal_sku`
generation moves server-side via an atomic `UPDATE ... RETURNING` on
`Category.next_sku_number` inside the same transaction as the `Material`
insert. New admin-only `/categories` CRUD router, `DELETE` blocked by an
explicit `COUNT` check.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 ORM, Alembic, Pydantic v2,
OR-Tools CP-SAT, pytest.

**Spec:** `docs/decisions/0034-material-category-entity-and-sku-autogeneration.md`
(primary), `docs/decisions/0028-strict-category-supplier-grouping.md`
(ILP mechanics being preserved, not reopened), `docs/decisions/0024-authentication-authorization.md`
§4/§5 (admin-only router pattern).

## Global Constraints

- Backend only — no frontend changes in this plan (ADR-0034 "Реализация... предмет отдельной задачи").
- `Category.sku_prefix` is immutable after creation — `CategoryUpdate` schema has no `sku_prefix` field at all, not just an ignored one.
- `internal_sku` is never client-supplied — removed from `MaterialCreate`/`MaterialUpdate` entirely.
- `solver.py`'s ILP mechanics (`diff[C][m]`, reference material, penalty formula, `CATEGORY_SPLIT_PENALTY_K`) do not change — only the source of the strictness boolean and the grouping key change.
- Every existing ADR-0028 test in `test_solver.py` must be rewritten 1:1 onto the new `MaterialInput` signature with the **same** expected result — regression, not new "similar" tests.
- `algorithm_version` (`"adr-0028-v1"`) is **not** bumped by this task, provided the regression tests pass with identical outcomes.
- Money/quantity math stays backend-only (CLAUDE.md principle 4) — not directly implicated here, but `internal_sku` assignment must be race-safe (row-level lock via `UPDATE ... RETURNING`), not merely "usually correct."
- Run the full existing regression suite, not a subset, per project instruction.
- Do not touch prod migrations/deploy or `.env`/secrets (CLAUDE.md).
- Do not run `--apply` on the dry-run backfill against the real catalog without explicit user confirmation after reviewing the dry-run report.

---

## Task 1: `Category` model + migration (a) — nullable `category_id`

**Files:**
- Create: `backend/app/models/category.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models/material.py`
- Create: `backend/alembic/versions/<hash>_add_category_table.py`
- Test: `backend/tests/models/test_category.py` (new — only if a `tests/models` dir convention doesn't exist, create it; otherwise put in `backend/tests/scripts/test_backfill_material_categories.py` fixtures, see Task 3)

**Interfaces:**
- Produces: `Category` ORM class with `id: uuid.UUID`, `name: str` (unique), `sku_prefix: str` (unique, `String(10)`), `requires_single_supplier: bool` (default `False`), `next_sku_number: int` (default `1`), `created_at: datetime`.
- Produces: `Material.category_id: uuid.UUID | None` (FK to `categories.id`, nullable in this migration), `Material.category: Mapped["Category"]` relationship (renamed from the old String column — the old String column is NOT dropped yet in this task, see step-by-step below: this task adds `category_id` alongside the existing `category` String column; Task 2 drops the String column and renames the relationship).

Because the ADR requires the relationship to end up named `Material.category` (so `material.category.name` reads naturally) but the existing column is *already* named `category` (String), this task cannot simply add a same-named relationship yet — SQLAlchemy would collide. Sequence chosen to avoid ever having a broken intermediate state:

- **Task 1**: add `Category` table + `Material.category_id` (nullable FK) + a *relationship* named `category_ref` (temporary name) pointing at `Category`. The old `category: Mapped[str | None]` String column and all its readers are untouched and still work.
- **Task 3** (solver/service refactor) and **Task 5/6** (matching.py/template.py) will be updated to use `category_id`/`requires_single_supplier`/`category_name` from `MaterialInput`, not `Material.category_ref` directly, except where the ORM object itself is read (matching.py, template.py) — those switch straight to the final relationship name once it exists.
- **Task 2** (second migration): after backfill, drop the String `category` column and *rename* the relationship from `category_ref` to `category` (a pure Python rename in the model, no migration involved — relationships aren't DB objects).

This avoids ever having two things named `category` on the model at once.

- [ ] **Step 1: Write `Category` model**

```python
# backend/app/models/category.py
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.material import Material


class Category(UUIDPKMixin, Base):
    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    sku_prefix: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    """Immutable after creation — see ADR-0034 п.5. internal_sku values already
    issued embed this prefix; CategoryUpdate has no field for it at all."""
    requires_single_supplier: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    """Drives ADR-0028 strict-category ILP grouping in solver.py — replaces the
    old STRICT_CATEGORIES code constant. See ADR-0034."""
    next_sku_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    """Atomically incremented via UPDATE ... RETURNING in the same transaction
    as Material creation — see ADR-0034 п.4. Never read-then-written as two
    separate statements."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    materials: Mapped[list["Material"]] = relationship(back_populates="category_ref")
```

- [ ] **Step 2: Add `category_id` + temporary `category_ref` relationship to `Material`**

Edit `backend/app/models/material.py` — add import and two new attributes, leave the existing `category: Mapped[str | None]` column untouched:

```python
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPKMixin

if TYPE_CHECKING:
    import uuid as _uuid

    from app.models.category import Category
    from app.models.price import Price
    from app.models.price_list import PriceListEntry
    from app.models.project import ProjectItem
    from app.models.supplier_material_alias import SupplierMaterialAlias


class Material(UUIDPKMixin, Base):
    __tablename__ = "materials"

    internal_sku: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    category_id: Mapped["_uuid.UUID | None"] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    """Nullable only during the ADR-0034 two-phase migration window (this
    revision). Made NOT NULL and the old `category` String column dropped in
    the follow-up revision, after backfill_material_categories.py --apply."""
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    color_options: Mapped[list[str] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    color_fragment: Mapped[str | None] = mapped_column(String(50), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

    category_ref: Mapped["Category | None"] = relationship(back_populates="materials")
    """Temporary name — renamed to `category` once the old String column is
    dropped in the follow-up migration (ADR-0034 п.1)."""
    prices: Mapped[list["Price"]] = relationship(back_populates="material")
    aliases: Mapped[list["SupplierMaterialAlias"]] = relationship(back_populates="material")
    project_items: Mapped[list["ProjectItem"]] = relationship(back_populates="material")
    price_list_entries: Mapped[list["PriceListEntry"]] = relationship(
        back_populates="matched_material"
    )
```

Keep every docstring already on the untouched fields (omitted above only for brevity — copy them across verbatim from the current file).

- [ ] **Step 3: Register `Category` in `app/models/__init__.py`**

```python
from app.models.allocation import AllocationLine, AllocationRun
from app.models.base import Base
from app.models.category import Category
from app.models.material import Material
...
__all__ = [
    "Base",
    "Category",
    "Supplier",
    "Material",
    ...
]
```//keep alphabetical/logical grouping consistent with existing order; insert `Category` right after `Base`, before `Material` (Material now depends on it via FK).

- [ ] **Step 4: Generate and hand-write the Alembic migration**

Run:

```
cd backend && alembic revision -m "add category table and material category_id"
```

Edit the generated file:

```python
"""add category table and material category_id

Revision ID: <generated>
Revises: <current head — run `alembic heads` to confirm>
Create Date: ...

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "<generated>"
down_revision: str | None = "<current head>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("sku_prefix", sa.String(length=10), nullable=False),
        sa.Column("requires_single_supplier", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("next_sku_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_categories_name"),
        sa.UniqueConstraint("sku_prefix", name="uq_categories_sku_prefix"),
    )
    op.add_column(
        "materials",
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_materials_category_id_categories",
        "materials",
        "categories",
        ["category_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_materials_category_id_categories", "materials", type_="foreignkey")
    op.drop_column("materials", "category_id")
    op.drop_table("categories")
```

- [ ] **Step 5: Run upgrade/downgrade cycle on dev DB**

```
cd backend && alembic upgrade head
cd backend && alembic downgrade -1
cd backend && alembic upgrade head
```

Expected: all three succeed with no errors; `categories` table and `materials.category_id` exist after the final `upgrade head`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/category.py backend/app/models/__init__.py backend/app/models/material.py backend/alembic/versions/
git commit -m "$(cat <<'EOF'
Add Category entity and Material.category_id (nullable) — ADR-0034 migration (a)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Backfill script `backfill_material_categories.py`

**Files:**
- Create: `backend/app/scripts/backfill_material_categories.py`
- Test: `backend/tests/scripts/test_backfill_material_categories.py`

**Interfaces:**
- Consumes: `Material.category` (String, still present), `Material.category_id` (nullable FK, from Task 1), `app.scripts.xlsx_price_matrix.CATEGORY_SKU_PREFIX: dict[str, str]`.
- Produces: `run_backfill(db: Session, apply: bool) -> BackfillReport` and `print_report(report: BackfillReport, apply: bool) -> None`, same shape/contract as `backfill_color_options.py`. `BackfillReport` carries: `category_rows: list[BackfillCategoryRow]` (name, sku_prefix, requires_single_supplier, material_count, next_sku_number), `null_category_id_before: int`, `null_category_id_after: int`, `verification_ok: bool`, `unknown_categories: list[str]` (categories found via `SELECT DISTINCT` not present in `CATEGORY_SKU_PREFIX` — triggers an explicit error, not a fallback).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/scripts/test_backfill_material_categories.py
"""Tests for the Category backfill — ADR-0034 п.2. Same savepoint-session
pattern as test_backfill_color_options.py: run_backfill's internal
db.commit() only releases a SAVEPOINT here, never touching the real catalog.
"""

import pytest
from sqlalchemy import event, select

from app.core.database import engine
from app.models import Category, Material
from app.scripts.backfill_material_categories import (
    CATEGORY_SKU_PREFIX,
    STRICT_CATEGORY_NAMES,
    UnknownCategoryError,
    run_backfill,
)


@pytest.fixture
def savepoint_session():
    connection = engine.connect()
    outer_transaction = connection.begin()

    from sqlalchemy.orm import Session

    session = Session(bind=connection, autoflush=False, autocommit=False)
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, transaction):
        if transaction.nested and not transaction._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


@pytest.fixture
def make_test_material(savepoint_session):
    def _make(sku, category, canonical_name=None):
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            category=category,
            unit="ft",
            attributes={},
        )
        savepoint_session.add(material)
        savepoint_session.flush()
        return material

    return _make


def _fixture_8_categories(make_test_material):
    """One material per each of the 8 real categories, mirroring the real
    catalog's category set exactly (ADR-0028 "Проверка Material.category на
    реальных данных")."""
    for i, cat in enumerate(CATEGORY_SKU_PREFIX):
        make_test_material(f"{CATEGORY_SKU_PREFIX[cat]}-{i:03d}", cat)


def test_backfill_dry_run_does_not_write_to_db(savepoint_session, make_test_material):
    make_test_material("DOOR-001", "Doors")

    report = run_backfill(savepoint_session, apply=False)

    assert any(row.name == "Doors" for row in report.category_rows)
    savepoint_session.expire_all()
    assert savepoint_session.scalars(select(Category)).all() == []


def test_backfill_apply_creates_exactly_8_categories_with_correct_flags(
    savepoint_session, make_test_material
):
    _fixture_8_categories(make_test_material)

    run_backfill(savepoint_session, apply=True)

    categories = {c.name: c for c in savepoint_session.scalars(select(Category)).all()}
    assert set(categories) == set(CATEGORY_SKU_PREFIX)
    for name, cat in categories.items():
        assert cat.requires_single_supplier == (name in STRICT_CATEGORY_NAMES)
        assert cat.sku_prefix == CATEGORY_SKU_PREFIX[name]


def test_backfill_links_materials_to_new_category_rows(savepoint_session, make_test_material):
    material = make_test_material("DOOR-001", "Doors")

    run_backfill(savepoint_session, apply=True)

    savepoint_session.refresh(material)
    assert material.category_id is not None
    category = savepoint_session.get(Category, material.category_id)
    assert category.name == "Doors"


def test_backfill_sets_next_sku_number_from_max_existing_suffix(
    savepoint_session, make_test_material
):
    make_test_material("DOOR-001", "Doors")
    make_test_material("DOOR-026", "Doors")
    make_test_material("DOOR-014", "Doors")  # out of order on purpose

    run_backfill(savepoint_session, apply=True)

    category = savepoint_session.scalars(
        select(Category).where(Category.name == "Doors")
    ).one()
    assert category.next_sku_number == 27


def test_backfill_next_sku_number_defaults_to_1_for_category_with_no_materials_matching_prefix_pattern(
    savepoint_session, make_test_material
):
    # SKU doesn't follow the {prefix}-{NNN} pattern -- must not crash the max-suffix scan.
    make_test_material("WEIRD-SKU", "Doors")

    run_backfill(savepoint_session, apply=True)

    category = savepoint_session.scalars(
        select(Category).where(Category.name == "Doors")
    ).one()
    assert category.next_sku_number == 1


def test_backfill_raises_on_category_not_in_sku_prefix_map(
    savepoint_session, make_test_material
):
    make_test_material("XXX-001", "NinthCategory")

    with pytest.raises(UnknownCategoryError):
        run_backfill(savepoint_session, apply=True)


def test_backfill_dry_run_reports_unknown_category_without_raising_or_writing(
    savepoint_session, make_test_material
):
    make_test_material("XXX-001", "NinthCategory")

    report = run_backfill(savepoint_session, apply=False)

    assert "NinthCategory" in report.unknown_categories
    savepoint_session.expire_all()
    assert savepoint_session.scalars(select(Category)).all() == []


def test_backfill_verification_matches_null_counts(savepoint_session, make_test_material):
    make_test_material("DOOR-001", "Doors")
    make_test_material("MISC-1", None)  # material with no category at all

    report = run_backfill(savepoint_session, apply=True)

    assert report.null_category_id_before == 1
    assert report.null_category_id_after == 1
    assert report.verification_ok is True


def test_backfill_verification_catches_corrupted_case_and_rolls_back(
    savepoint_session, make_test_material, monkeypatch
):
    """Artificially break the verification invariant: patch run_backfill's
    UPDATE step so one material with a non-null category is deliberately left
    with category_id NULL, then confirm the script detects the mismatch and
    (in --apply mode) rolls back rather than committing a partial result."""
    make_test_material("DOOR-001", "Doors")
    make_test_material("DOOR-002", "Doors")

    import app.scripts.backfill_material_categories as mod

    original_link = mod._link_materials_to_categories

    def _broken_link(db, category_by_name):
        original_link(db, category_by_name)
        # Undo the link for one material to simulate a missed row.
        stray = db.scalars(select(Material).where(Material.internal_sku == "DOOR-002")).one()
        stray.category_id = None

    monkeypatch.setattr(mod, "_link_materials_to_categories", _broken_link)

    report = run_backfill(savepoint_session, apply=True)

    assert report.verification_ok is False
    savepoint_session.expire_all()
    assert savepoint_session.scalars(select(Category)).all() == []


def test_backfill_is_idempotent_categories_not_duplicated_on_second_run(
    savepoint_session, make_test_material
):
    make_test_material("DOOR-001", "Doors")

    run_backfill(savepoint_session, apply=True)
    savepoint_session.commit()
    report_2 = run_backfill(savepoint_session, apply=True)

    categories = savepoint_session.scalars(
        select(Category).where(Category.name == "Doors")
    ).all()
    assert len(categories) == 1
    assert report_2.verification_ok is True
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && python -m pytest tests/scripts/test_backfill_material_categories.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.scripts.backfill_material_categories'`.

- [ ] **Step 3: Implement the backfill script**

```python
# backend/app/scripts/backfill_material_categories.py
"""One-time backfill: creates Category rows from the existing distinct
Material.category string values and links Material.category_id — see
ADR-0034 п.2. Same dry-run/--apply shape as backfill_color_options.py.

Critical difference from backfill_color_options.py: this backfill sets
requires_single_supplier, which directly drives the ILP solver's strict-
category grouping (ADR-0028) for the whole catalog from the moment --apply
runs. The dry-run report must be reviewed against the known set
{Doors, Gutter, Profil, Mesh, Roof panels} -> True before running --apply.

Usage:
    python -m app.scripts.backfill_material_categories            # dry-run
    python -m app.scripts.backfill_material_categories --apply    # write
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Category, Material
from app.scripts.xlsx_price_matrix import CATEGORY_SKU_PREFIX

STRICT_CATEGORY_NAMES = {"Doors", "Gutter", "Profil", "Mesh", "Roof panels"}
"""ADR-0028's five visually-facing categories -- requires_single_supplier=True
after this backfill. Lives here, not in solver.py: after ADR-0034, solver.py
no longer knows category names at all, only category_id + a bool it reads
from the DB. This constant exists solely to seed that DB value once."""

_SKU_SUFFIX_RE = re.compile(r"-(\d+)$")


class UnknownCategoryError(Exception):
    """A Material.category value has no entry in CATEGORY_SKU_PREFIX -- must
    not silently fall back to MISC/an arbitrary prefix, see ADR-0034 п.2."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(
            f"Category {category!r} found in materials but missing from "
            f"CATEGORY_SKU_PREFIX -- refusing to guess a sku_prefix"
        )


@dataclass
class BackfillCategoryRow:
    name: str
    sku_prefix: str
    requires_single_supplier: bool
    material_count: int
    next_sku_number: int


@dataclass
class BackfillReport:
    category_rows: list[BackfillCategoryRow] = field(default_factory=list)
    unknown_categories: list[str] = field(default_factory=list)
    null_category_id_before: int = 0
    null_category_id_after: int = 0
    verification_ok: bool = True


def _max_sku_suffix(materials: list[Material]) -> int:
    best = 0
    for material in materials:
        match = _SKU_SUFFIX_RE.search(material.internal_sku)
        if match:
            best = max(best, int(match.group(1)))
    return best


def _link_materials_to_categories(db: Session, category_by_name: dict[str, Category]) -> None:
    materials = db.scalars(select(Material).where(Material.category.is_not(None))).all()
    for material in materials:
        material.category_id = category_by_name[material.category].id


def run_backfill(db: Session, apply: bool) -> BackfillReport:
    report = BackfillReport()

    report.null_category_id_before = db.scalar(
        select(Material).where(Material.category.is_(None))
    ) and db.query(Material).filter(Material.category.is_(None)).count() or db.query(
        Material
    ).filter(Material.category.is_(None)).count()
    report.null_category_id_before = (
        db.query(Material).filter(Material.category.is_(None)).count()
    )

    distinct_categories = [
        row[0]
        for row in db.execute(
            select(Material.category).distinct().where(Material.category.is_not(None))
        ).all()
    ]

    unknown = [c for c in distinct_categories if c not in CATEGORY_SKU_PREFIX]
    if unknown:
        report.unknown_categories = unknown
        if apply:
            raise UnknownCategoryError(unknown[0])
        return report

    category_by_name: dict[str, Category] = {}
    for name in distinct_categories:
        materials = db.scalars(select(Material).where(Material.category == name)).all()
        sku_prefix = CATEGORY_SKU_PREFIX[name]
        next_sku_number = _max_sku_suffix(materials) + 1
        requires_single_supplier = name in STRICT_CATEGORY_NAMES

        report.category_rows.append(
            BackfillCategoryRow(
                name=name,
                sku_prefix=sku_prefix,
                requires_single_supplier=requires_single_supplier,
                material_count=len(materials),
                next_sku_number=next_sku_number,
            )
        )

        if apply:
            category = Category(
                name=name,
                sku_prefix=sku_prefix,
                requires_single_supplier=requires_single_supplier,
                next_sku_number=next_sku_number,
            )
            db.add(category)
            db.flush()
            category_by_name[name] = category

    if apply:
        _link_materials_to_categories(db, category_by_name)
        db.flush()

        report.null_category_id_after = (
            db.query(Material).filter(Material.category_id.is_(None)).count()
        )
        report.verification_ok = (
            report.null_category_id_after == report.null_category_id_before
        )

        if not report.verification_ok:
            db.rollback()
        else:
            db.commit()
    else:
        report.null_category_id_after = report.null_category_id_before

    return report


def print_report(report: BackfillReport, apply: bool) -> None:
    print("=" * 70)
    print(f"Категорий найдено: {len(report.category_rows)}")
    print("=" * 70)
    for row in report.category_rows:
        print(
            f"  {row.name!r} -> sku_prefix={row.sku_prefix!r}, "
            f"requires_single_supplier={row.requires_single_supplier}, "
            f"материалов={row.material_count}, next_sku_number={row.next_sku_number}"
        )
    print()

    if report.unknown_categories:
        print("=" * 70)
        print(f"ОШИБКА: категории вне CATEGORY_SKU_PREFIX: {report.unknown_categories}")
        print("=" * 70)
        return

    print(
        "Проверь вручную: {Doors, Gutter, Profil, Mesh, Roof panels} -> True, "
        "остальные -> False, и что нет неожиданной 9-й категории."
    )
    print(
        f"category_id IS NULL до операции: {report.null_category_id_before}, "
        f"после: {report.null_category_id_after}"
    )
    if not report.verification_ok:
        print("ОШИБКА: несоответствие количества NULL -- откат" + (" выполнен" if apply else " (dry-run, ничего не менялось)"))
    elif apply:
        print(f"Записано в БД: {len(report.category_rows)} категорий.")
    else:
        print("Dry-run: ничего не изменено. Перезапусти с --apply, чтобы записать.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Реально записать Category и Material.category_id (без флага — dry-run).",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        report = run_backfill(db, apply=args.apply)
        print_report(report, apply=args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

Clean up the accidental duplicate/dead line computing `null_category_id_before` (leftover from drafting) before running — keep only the single correct assignment:

```python
    report.null_category_id_before = (
        db.query(Material).filter(Material.category.is_(None)).count()
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd backend && python -m pytest tests/scripts/test_backfill_material_categories.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/backfill_material_categories.py backend/tests/scripts/test_backfill_material_categories.py
git commit -m "$(cat <<'EOF'
Add dry-run/--apply backfill script for Category (ADR-0034 п.2)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Refactor `solver.py` — remove `STRICT_CATEGORIES`, group by `category_id`

**Files:**
- Modify: `backend/app/allocation/types.py`
- Modify: `backend/app/allocation/solver.py`
- Modify: `backend/tests/allocation/test_solver.py`

**Interfaces:**
- Produces: `MaterialInput(material_id: str, quantity: int, category_id: str | None = None, requires_single_supplier: bool = False, category_name: str | None = None)` — replaces the old `category: str | None` field.
- Consumes (Task 4): `service.py` constructs `MaterialInput` with all three new fields.

- [ ] **Step 1: Update `MaterialInput` in `types.py`**

```python
@dataclass(frozen=True)
class MaterialInput:
    material_id: str
    quantity: int
    category_id: str | None = None
    """Grouping key for ADR-0028 strict-category linking -- stable across a
    Category rename (FK id, not name). None only for materials somehow
    without a category (shouldn't occur after ADR-0034's NOT NULL, kept
    optional here because callers like preprocess.py don't care about
    category at all)."""
    requires_single_supplier: bool = False
    """Category.requires_single_supplier -- the only thing the solver needs
    to decide whether to group this material's category. See ADR-0034 §3."""
    category_name: str | None = None
    """Display-only -- used for split_categories text, never for grouping
    logic (category_id is the grouping key). See ADR-0034 §3."""
```

- [ ] **Step 2: Run existing tests to see the expected failures (signature mismatch)**

```
cd backend && python -m pytest tests/allocation/test_solver.py -v
```
Expected: `TypeError: MaterialInput.__init__() got an unexpected keyword argument 'category'` across the ADR-0028 tests, confirming they need rewriting (next step).

- [ ] **Step 3: Rewrite the 9 ADR-0028 tests onto the new signature, delete the 2 constant tests**

In `backend/tests/allocation/test_solver.py`:

Remove this import line (no longer exists):
```python
from app.allocation.solver import STRICT_CATEGORIES, solve_allocation
from app.scripts.xlsx_price_matrix import CATEGORY_SKU_PREFIX
```
Replace with:
```python
from app.allocation.solver import solve_allocation
```

Delete these two tests entirely (superseded by Task 2's backfill tests, which already assert the same 5-categories invariant against `STRICT_CATEGORY_NAMES`):
```python
def test_strict_categories_constant_matches_spec(): ...
def test_strict_categories_are_a_subset_of_real_catalog_categories(): ...
```

Rewrite every other `category="X"` kwarg to the new fields. Reference material selection in `solver.py` will key off `category_id` (min by `material_id` within materials sharing the same `category_id`) — use a stable fake UUID-like string per category so `min()` ordering is unaffected (material_id strings like `"d1"`/`"d2"` already sort deterministically, unchanged).

```python
def test_strict_category_all_materials_at_one_supplier_stays_together():
    materials = [
        MaterialInput(material_id="d1", quantity=1, category_id="doors", requires_single_supplier=True),
        MaterialInput(material_id="d2", quantity=1, category_id="doors", requires_single_supplier=True),
    ]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=0),
        SupplierInput(supplier_id="s2", flat_fee_cents=0, free_shipping_threshold_cents=0),
    ]
    prices = [
        PriceInput(material_id="d1", supplier_id="s1", unit_price_cents=500, availability=10),
        PriceInput(material_id="d2", supplier_id="s1", unit_price_cents=500, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assignments = {line.material_id: line.supplier_id for line in result.lines}
    assert assignments == {"d1": "s1", "d2": "s1"}


def test_strict_category_prefers_single_supplier_at_moderate_price_difference():
    materials = [
        MaterialInput(material_id="d1", quantity=1, category_id="doors", requires_single_supplier=True),
        MaterialInput(material_id="d2", quantity=1, category_id="doors", requires_single_supplier=True),
    ]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=1000, free_shipping_threshold_cents=None),
        SupplierInput(supplier_id="s2", flat_fee_cents=1000, free_shipping_threshold_cents=None),
    ]
    prices = [
        PriceInput(material_id="d1", supplier_id="s1", unit_price_cents=100, availability=10),
        PriceInput(material_id="d1", supplier_id="s2", unit_price_cents=110, availability=10),
        PriceInput(material_id="d2", supplier_id="s1", unit_price_cents=300, availability=10),
        PriceInput(material_id="d2", supplier_id="s2", unit_price_cents=290, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assignments = {line.material_id: line.supplier_id for line in result.lines}
    assert len(set(assignments.values())) == 1


def test_strict_category_splits_when_price_difference_is_large_enough():
    materials = [
        MaterialInput(material_id="d1", quantity=1, category_id="doors", requires_single_supplier=True),
        MaterialInput(material_id="d2", quantity=1, category_id="doors", requires_single_supplier=True),
    ]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=100, free_shipping_threshold_cents=None),
        SupplierInput(supplier_id="s2", flat_fee_cents=100, free_shipping_threshold_cents=None),
    ]
    prices = [
        PriceInput(material_id="d1", supplier_id="s1", unit_price_cents=100, availability=10),
        PriceInput(material_id="d1", supplier_id="s2", unit_price_cents=100_000, availability=10),
        PriceInput(material_id="d2", supplier_id="s1", unit_price_cents=100_000, availability=10),
        PriceInput(material_id="d2", supplier_id="s2", unit_price_cents=100, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assignments = {line.material_id: line.supplier_id for line in result.lines}
    assert assignments == {"d1": "s1", "d2": "s2"}


def test_strict_category_no_single_supplier_covers_whole_category_stays_feasible():
    materials = [
        MaterialInput(material_id="mesh1", quantity=1, category_id="mesh", requires_single_supplier=True),
        MaterialInput(material_id="mesh2", quantity=1, category_id="mesh", requires_single_supplier=True),
    ]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=0),
        SupplierInput(supplier_id="s2", flat_fee_cents=0, free_shipping_threshold_cents=0),
    ]
    prices = [
        PriceInput(material_id="mesh1", supplier_id="s1", unit_price_cents=500, availability=10),
        PriceInput(material_id="mesh2", supplier_id="s2", unit_price_cents=600, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assignments = {line.material_id: line.supplier_id for line in result.lines}
    assert assignments == {"mesh1": "s1", "mesh2": "s2"}


def test_non_strict_category_split_across_suppliers_is_unpenalized():
    materials = [
        MaterialInput(material_id="m1", quantity=1, category_id="connectors", requires_single_supplier=False),
        MaterialInput(material_id="m2", quantity=1, category_id="connectors", requires_single_supplier=False),
    ]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=1500),
        SupplierInput(supplier_id="s2", flat_fee_cents=1000, free_shipping_threshold_cents=100_000),
    ]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=1000, availability=10),
        PriceInput(material_id="m2", supplier_id="s1", unit_price_cents=600, availability=10),
        PriceInput(material_id="m2", supplier_id="s2", unit_price_cents=400, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assert result.total_cents == 1600
    assignments = {line.material_id: line.supplier_id for line in result.lines}
    assert assignments == {"m1": "s1", "m2": "s1"}


def test_strict_category_asymmetric_pair_mechanism_registers_mismatch_via_penalty():
    materials = [
        MaterialInput(material_id="d1", quantity=1, category_id="doors", requires_single_supplier=True),
        MaterialInput(material_id="d2", quantity=1, category_id="doors", requires_single_supplier=True),
    ]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=None),
        SupplierInput(supplier_id="s2", flat_fee_cents=0, free_shipping_threshold_cents=None),
    ]
    prices = [
        PriceInput(material_id="d1", supplier_id="s1", unit_price_cents=100_000, availability=10),
        PriceInput(material_id="d1", supplier_id="s2", unit_price_cents=100, availability=10),
        PriceInput(material_id="d2", supplier_id="s1", unit_price_cents=200, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assignments = {line.material_id: line.supplier_id for line in result.lines}
    assert assignments == {"d1": "s2", "d2": "s1"}


def test_strict_category_asymmetric_pair_still_penalized_at_moderate_gap():
    materials = [
        MaterialInput(material_id="d1", quantity=1, category_id="doors", requires_single_supplier=True),
        MaterialInput(material_id="d2", quantity=1, category_id="doors", requires_single_supplier=True),
    ]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=1000, free_shipping_threshold_cents=None),
        SupplierInput(supplier_id="s2", flat_fee_cents=1000, free_shipping_threshold_cents=None),
    ]
    prices = [
        PriceInput(material_id="d1", supplier_id="s1", unit_price_cents=200, availability=10),
        PriceInput(material_id="d1", supplier_id="s2", unit_price_cents=100, availability=10),
        PriceInput(material_id="d2", supplier_id="s1", unit_price_cents=200, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assignments = {line.material_id: line.supplier_id for line in result.lines}
    assert assignments == {"d1": "s1", "d2": "s1"}
```

Note: `test_strict_category_all_materials_at_one_supplier_stays_together`'s original assertion style is kept; the "prefers_single_supplier" test's assertion `assert len(set(assignments.values())) == 1` stays the same shape as the original (it never asserted which supplier, only that both land together) — keep that.

Also update the 8th (`d1`,`d2`) reference-material selection concern: `solver.py`'s "opорный материал" is chosen via `min(cat_material_ids)` (min of the material_id strings) inside a `category_id`-keyed group — with `"d1"`/`"d2"` as material_ids this is unaffected by the category_id rename to `"doors"`. Verify this holds by inspection during Step 5 (no behavior change expected).

- [ ] **Step 4: Update `solver.py`**

```python
"""ILP-постановка подбора поставщика — реализация ADR-0002 через OR-Tools CP-SAT.
...
"""

from __future__ import annotations

from ortools.sat.python import cp_model

from app.allocation.types import (
    AllocationInput,
    AllocationLineResult,
    AllocationResult,
    SupplierSummary,
)

_STATUS_NAMES = {
    cp_model.OPTIMAL: "OPTIMAL",
    cp_model.FEASIBLE: "FEASIBLE",
    cp_model.INFEASIBLE: "INFEASIBLE",
    cp_model.MODEL_INVALID: "MODEL_INVALID",
    cp_model.UNKNOWN: "UNKNOWN",
}

CATEGORY_SPLIT_PENALTY_K = 4
"""Unchanged by ADR-0034 -- see ADR-0028 §2."""


def solve_allocation(data: AllocationInput) -> AllocationResult:
    if not data.materials:
        return AllocationResult(status="NO_SOLVABLE_MATERIALS")

    qty = {m.material_id: m.quantity for m in data.materials}
    material_ids = list(qty.keys())

    price: dict[tuple[str, str], int] = {}
    for p in data.prices:
        if p.material_id not in qty:
            continue
        if p.availability is not None and p.availability < qty[p.material_id]:
            continue
        price[(p.material_id, p.supplier_id)] = p.unit_price_cents

    suppliers_by_id = {s.supplier_id: s for s in data.suppliers}
    supplier_ids = sorted({s for (_, s) in price})

    model = cp_model.CpModel()

    x: dict[tuple[str, str], cp_model.IntVar] = {}
    for m_id in material_ids:
        for s_id in supplier_ids:
            if (m_id, s_id) in price:
                x[(m_id, s_id)] = model.new_bool_var(f"x_{m_id}_{s_id}")

    for m_id in material_ids:
        candidates = [x[(m_id, s_id)] for s_id in supplier_ids if (m_id, s_id) in x]
        model.add(sum(candidates) == 1)

    # ADR-0028 §1/§2, ADR-0034 §3: grouping key is category_id (stable across
    # a Category rename), strictness flag is requires_single_supplier (from
    # Category.requires_single_supplier via MaterialInput, not a name-set
    # membership test). ILP mechanics (diff[C][m], reference material,
    # soft-only penalty) are unchanged from ADR-0028.
    materials_by_category: dict[str, list[str]] = {}
    for m in data.materials:
        if m.requires_single_supplier and m.category_id is not None:
            materials_by_category.setdefault(m.category_id, []).append(m.material_id)

    diff: dict[tuple[str, str], cp_model.IntVar] = {}  # (category_id, m_id) -> diff[C][m]
    for cat_id, cat_material_ids in materials_by_category.items():
        if len(cat_material_ids) < 2:
            continue
        ref_m_id = min(cat_material_ids)
        for m_id in cat_material_ids:
            if m_id == ref_m_id:
                continue
            diff_var = model.new_bool_var(f"diff_{cat_id}_{m_id}")
            diff[(cat_id, m_id)] = diff_var
            for s_id in supplier_ids:
                ref_var = x.get((ref_m_id, s_id))
                m_var = x.get((m_id, s_id))
                if ref_var is not None and m_var is not None:
                    model.add(diff_var >= ref_var - m_var)
                    model.add(diff_var >= m_var - ref_var)
                elif ref_var is not None:
                    model.add(diff_var >= ref_var)
                elif m_var is not None:
                    model.add(diff_var >= m_var)

    y: dict[str, cp_model.IntVar] = {s_id: model.new_bool_var(f"y_{s_id}") for s_id in supplier_ids}

    for (_m_id, s_id), var in x.items():
        model.add(var <= y[s_id])

    order_total: dict[str, cp_model.LinearExpr] = {}
    max_order_total: dict[str, int] = {}
    for s_id in supplier_ids:
        terms = [
            x[(m_id, s_id)] * price[(m_id, s_id)] * qty[m_id]
            for m_id in material_ids
            if (m_id, s_id) in x
        ]
        order_total[s_id] = sum(terms)
        max_order_total[s_id] = sum(
            price[(m_id, s_id)] * qty[m_id] for m_id in material_ids if (m_id, s_id) in x
        )

    for s_id in supplier_ids:
        min_amount = suppliers_by_id[s_id].per_order_min_amount_cents
        if min_amount > 0:
            model.add(order_total[s_id] >= min_amount * y[s_id])

    free: dict[str, cp_model.IntVar] = {}
    z: dict[str, cp_model.IntVar] = {}
    epsilon_cents = 1
    for s_id in supplier_ids:
        threshold = suppliers_by_id[s_id].free_shipping_threshold_cents
        free_var = model.new_bool_var(f"free_{s_id}")
        free[s_id] = free_var

        if threshold is None:
            model.add(free_var == 0)
        elif threshold == 0:
            model.add(free_var == y[s_id])
        else:
            big_m = threshold + max_order_total[s_id]
            model.add(order_total[s_id] >= threshold - big_m * (1 - free_var))
            model.add(order_total[s_id] <= threshold - epsilon_cents + big_m * free_var)
            model.add(free_var <= y[s_id])

        z_var = model.new_bool_var(f"z_{s_id}")
        z[s_id] = z_var
        model.add(z_var <= y[s_id])
        model.add(z_var <= 1 - free_var)
        model.add(z_var >= y[s_id] - free_var)

    price_terms = [x[(m_id, s_id)] * price[(m_id, s_id)] * qty[m_id] for (m_id, s_id) in x]
    delivery_terms = [z[s_id] * suppliers_by_id[s_id].flat_fee_cents for s_id in supplier_ids]

    penalty_terms: list[cp_model.LinearExpr] = []
    if diff:
        avg_flat_fee_cents = sum(
            suppliers_by_id[s_id].flat_fee_cents for s_id in supplier_ids
        ) / len(supplier_ids)
        category_split_penalty = round(CATEGORY_SPLIT_PENALTY_K * avg_flat_fee_cents)
        penalty_terms = [category_split_penalty * diff_var for diff_var in diff.values()]

    model.minimize(sum(price_terms) + sum(delivery_terms) + sum(penalty_terms))

    solver = cp_model.CpSolver()
    solver.parameters.random_seed = 1
    solver.parameters.num_search_workers = 1
    status_code = solver.solve(model)
    status = _STATUS_NAMES.get(status_code, "UNKNOWN")

    if status not in ("OPTIMAL", "FEASIBLE"):
        return AllocationResult(status=status)

    lines: list[AllocationLineResult] = []
    for (m_id, s_id), var in x.items():
        if solver.value(var):
            unit_price = price[(m_id, s_id)]
            quantity = qty[m_id]
            lines.append(
                AllocationLineResult(
                    material_id=m_id,
                    supplier_id=s_id,
                    quantity=quantity,
                    unit_price_cents=unit_price,
                    line_total_cents=unit_price * quantity,
                )
            )

    active_supplier_ids = {line.supplier_id for line in lines}

    total_cents = sum(line.line_total_cents for line in lines) + sum(
        suppliers_by_id[s_id].flat_fee_cents
        for s_id in active_supplier_ids
        if not solver.value(free[s_id])
    )

    supplier_summaries: list[SupplierSummary] = []
    for s_id in sorted(active_supplier_ids):
        free_achieved = bool(solver.value(free[s_id]))
        supplier_summaries.append(
            SupplierSummary(
                supplier_id=s_id,
                goods_total_cents=solver.value(order_total[s_id]),
                delivery_fee_cents=0
                if free_achieved
                else suppliers_by_id[s_id].flat_fee_cents,
                free_shipping_achieved=free_achieved,
            )
        )

    return AllocationResult(
        status=status,
        lines=lines,
        supplier_summaries=supplier_summaries,
        total_cents=total_cents,
    )
```

Preserve the existing top-of-function docstring and every ADR-0028-referencing comment inline — trimmed above for plan brevity only; copy them verbatim into the real file, updating "STRICT_CATEGORIES"/"category_map" language to reflect the new `category_id`/`requires_single_supplier` source per ADR-0034 §3.

- [ ] **Step 5: Run the full solver test suite**

```
cd backend && python -m pytest tests/allocation/test_solver.py -v
```
Expected: all tests PASS, including every rewritten ADR-0028 test with unchanged expected outcomes.

- [ ] **Step 6: Add the new default-False coverage test**

Add to `test_solver.py`:

```python
def test_new_category_with_requires_single_supplier_false_by_default_is_unpenalized():
    # ADR-0034 §3.1: a brand-new Category with requires_single_supplier=False
    # (the schema default) must behave exactly like today's non-strict
    # categories -- no grouping, no penalty -- without anyone having to
    # explicitly opt out.
    materials = [
        MaterialInput(material_id="m1", quantity=1, category_id="new-cat", requires_single_supplier=False),
        MaterialInput(material_id="m2", quantity=1, category_id="new-cat", requires_single_supplier=False),
    ]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=1500),
        SupplierInput(supplier_id="s2", flat_fee_cents=1000, free_shipping_threshold_cents=100_000),
    ]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=1000, availability=10),
        PriceInput(material_id="m2", supplier_id="s1", unit_price_cents=600, availability=10),
        PriceInput(material_id="m2", supplier_id="s2", unit_price_cents=400, availability=10),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "OPTIMAL"
    assert result.total_cents == 1600
    assignments = {line.material_id: line.supplier_id for line in result.lines}
    assert assignments == {"m1": "s1", "m2": "s1"}
```

Run again to confirm it passes:
```
cd backend && python -m pytest tests/allocation/test_solver.py -v
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/allocation/types.py backend/app/allocation/solver.py backend/tests/allocation/test_solver.py
git commit -m "$(cat <<'EOF'
Refactor solver.py to group by category_id/requires_single_supplier — remove STRICT_CATEGORIES (ADR-0034 §3)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Refactor `service.py::_compute_split_categories` + `MaterialInput` construction

**Files:**
- Modify: `backend/app/allocation/service.py`
- Modify: `backend/tests/allocation/conftest.py` (add `make_category` fixture, update `make_material` to take `category_id`)
- Modify: `backend/tests/allocation/test_service.py`
- Modify: `backend/tests/allocation/test_override.py`

**Interfaces:**
- Consumes: `Category` model (Task 1), `MaterialInput` new fields (Task 3).
- Produces: `_compute_split_categories(db, run_id) -> list[str]` — same return shape (category **names**, for UI text) as before, but computed via a `Category` join, no `STRICT_CATEGORIES` import.

- [ ] **Step 1: Update `tests/allocation/conftest.py` fixtures**

Add a `make_category` fixture and change `make_material` to accept a `Category` object (or `category_id`) instead of a bare string:

```python
# backend/tests/allocation/conftest.py — add Category import
from app.models import (
    AllocationLine,
    AllocationRun,
    Category,
    Material,
    Order,
    OrderItem,
    Price,
    Project,
    ProjectItem,
    Supplier,
    User,
    UserSession,
)
```

Add `category_ids` bookkeeping list to `db_session` teardown (mirrors the existing `material_ids`/`supplier_ids` pattern):

```python
@pytest.fixture
def db_session():
    session = SessionLocal()
    project_ids: list = []
    material_ids: list = []
    supplier_ids: list = []
    user_ids: list = []
    category_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, project_ids, material_ids, supplier_ids, user_ids, category_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
        # ... existing project/order/run cleanup unchanged ...
        if material_ids:
            session.query(Price).filter(Price.material_id.in_(material_ids)).delete(
                synchronize_session=False
            )
            session.query(Material).filter(Material.id.in_(material_ids)).delete(
                synchronize_session=False
            )
        if supplier_ids:
            session.query(Price).filter(Price.supplier_id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
            session.query(Supplier).filter(Supplier.id.in_(supplier_ids)).delete(
                synchronize_session=False
            )
        if category_ids:
            session.query(Category).filter(Category.id.in_(category_ids)).delete(
                synchronize_session=False
            )
        if user_ids:
            session.query(UserSession).filter(UserSession.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            session.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        session.commit()
        session.close()
```

Update every other fixture's unpacking line (`make_user`, `make_session`, `make_supplier`, `make_material`, `make_price`, `make_project`) to account for the new 6th tuple element — e.g. `session, *_rest, user_ids = db_session` style ones are unaffected, but any that destructure by position (`session, _project_ids, material_ids, _supplier_ids, _user_ids = db_session`) must become `session, _project_ids, material_ids, _supplier_ids, _user_ids, _category_ids = db_session`.

Add `make_category`:

```python
@pytest.fixture
def make_category(db_session):
    session, _project_ids, _material_ids, _supplier_ids, _user_ids, category_ids = db_session
    counter = {"n": 0}

    def _make(name=None, sku_prefix=None, requires_single_supplier=False):
        counter["n"] += 1
        name = name or f"Test Category {counter['n']}"
        sku_prefix = sku_prefix or f"TC{counter['n']}"
        category = Category(
            name=name, sku_prefix=sku_prefix, requires_single_supplier=requires_single_supplier
        )
        session.add(category)
        session.flush()
        category_ids.append(category.id)
        return category

    return _make
```

Update `make_material` to accept a `Category` object:

```python
@pytest.fixture
def make_material(db_session):
    session, _project_ids, material_ids, _supplier_ids, _user_ids, _category_ids = db_session
    counter = {"n": 0}

    def _make(sku=None, unit="ft", category=None):
        counter["n"] += 1
        sku = sku or f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        material = Material(
            internal_sku=sku,
            canonical_name=sku,
            category_id=category.id if category is not None else None,
            unit=unit,
            attributes={},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make
```

Update `make_project`'s and any other fixture's destructuring line the same way (append `_category_ids`).

- [ ] **Step 2: Update `test_service.py` and `test_override.py` call sites**

Every `make_material(category="Doors")` / `make_material(category="Mesh")` call becomes `make_material(category=make_category(name="Doors", requires_single_supplier=True))` (or reuse one `doors = make_category(...)` across two `make_material` calls in the same test where the original shared the same category string). Concretely in `test_service.py`:

```python
def test_run_allocation_leaves_split_categories_empty_when_category_unified(
    db_session, make_supplier, make_material, make_category, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    doors = make_category(name="Doors", requires_single_supplier=True)
    door1 = make_material(category=doors)
    door2 = make_material(category=doors)
    make_price(door1, supplier, price=5.00, availability=10)
    make_price(door2, supplier, price=6.00, availability=10)
    project = make_project([(door1, 1), (door2, 1)])

    run = run_allocation(session, project.id)

    assert run.status == "ok"
    assert run.split_categories == []


def test_run_allocation_reports_split_categories_when_category_actually_split(
    db_session, make_supplier, make_material, make_category, make_price, make_project
):
    session, *_ = db_session
    s1 = make_supplier(name="Supplier One", flat_fee=0.0, free_shipping_threshold=0.0)
    s2 = make_supplier(name="Supplier Two", flat_fee=0.0, free_shipping_threshold=0.0)
    mesh = make_category(name="Mesh", requires_single_supplier=True)
    mesh1 = make_material(category=mesh)
    mesh2 = make_material(category=mesh)
    make_price(mesh1, s1, price=5.00, availability=10)
    make_price(mesh2, s2, price=6.00, availability=10)
    project = make_project([(mesh1, 1), (mesh2, 1)])

    run = run_allocation(session, project.id)

    assert run.status == "ok"
    assert run.split_categories == ["Mesh"]
```

Apply the equivalent transformation to `test_override.py`'s `test_override_recomputes_split_categories`:

```python
def test_override_recomputes_split_categories(
    db_session, make_supplier, make_material, make_category, make_price, make_project
):
    session, *_ = db_session
    old_supplier = make_supplier(name="Old Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    new_supplier = make_supplier(name="New Supplier", flat_fee=0.0, free_shipping_threshold=0.0)
    doors = make_category(name="Doors", requires_single_supplier=True)
    door1 = make_material(category=doors)
    door2 = make_material(category=doors)
    make_price(door1, old_supplier, price=5.00, availability=10)
    make_price(door2, old_supplier, price=6.00, availability=10)
    make_price(door1, new_supplier, price=7.00, availability=10)
    project = make_project([(door1, 1), (door2, 1)])

    run = run_allocation(session, project.id)
    assert run.split_categories == []
    line = (
        session.query(AllocationLine)
        .filter_by(allocation_run_id=run.id, material_id=door1.id)
        .one()
    )

    override_allocation_line_supplier(session, run.id, line.id, new_supplier.id)
    session.refresh(run)

    assert run.split_categories == ["Doors"]
```

Every other `make_material()` call without a `category=` kwarg is unaffected (defaults to `category=None` → `category_id=None`) — but note Task 4 Step 3 below makes `_compute_split_categories`'s query an INNER JOIN on `Category`, so a `NULL category_id` material simply never contributes to `split_categories` (equivalent to today's "category not in STRICT_CATEGORIES" skip). No further changes needed to those tests.

- [ ] **Step 3: Rewrite `_compute_split_categories` and `MaterialInput` construction in `service.py`**

```python
# backend/app/allocation/service.py — imports
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.allocation.preprocess import split_orphaned_materials
from app.allocation.solver import solve_allocation
from app.allocation.tax import calculate_tax
from app.allocation.types import AllocationInput, MaterialInput, PriceInput, SupplierInput
from app.models import (
    AllocationLine,
    AllocationRun,
    Category,
    Material,
    Price,
    Project,
    ProjectItem,
    Supplier,
)
```

Update the `MaterialInput` construction inside `run_allocation`:

```python
    materials = [
        MaterialInput(
            material_id=str(item.material_id),
            quantity=item.quantity,
            category_id=str(item.material.category_id) if item.material.category_id else None,
            requires_single_supplier=(
                item.material.category_ref.requires_single_supplier
                if item.material.category_ref is not None
                else False
            ),
            category_name=(
                item.material.category_ref.name
                if item.material.category_ref is not None
                else None
            ),
        )
        for item in project_items
    ]
```

Rewrite `_compute_split_categories`:

```python
def _compute_split_categories(db: Session, run_id: uuid.UUID) -> list[str]:
    """ADR-0028 §4, updated by ADR-0034 §3: a strict category is "split" for
    this run if the project's current AllocationLine rows for that category
    (joined through Material.category_id to Category) are assigned to more
    than one distinct supplier. requires_single_supplier now comes from the
    Category row itself (read the same way solver.py reads it), not a
    hardcoded name-set constant -- the two call sites must never diverge in
    how they read this flag, see ADR-0034 "Контекст"."""
    rows = db.execute(
        select(Category.name, Category.requires_single_supplier, AllocationLine.supplier_id)
        .join(Material, Material.category_id == Category.id)
        .join(AllocationLine, AllocationLine.material_id == Material.id)
        .where(AllocationLine.allocation_run_id == run_id)
    ).all()

    suppliers_by_category: dict[str, set[uuid.UUID]] = {}
    for category_name, requires_single_supplier, supplier_id in rows:
        if not requires_single_supplier:
            continue
        suppliers_by_category.setdefault(category_name, set()).add(supplier_id)

    return sorted(
        category_name
        for category_name, supplier_ids in suppliers_by_category.items()
        if len(supplier_ids) > 1
    )
```

Also update `ALGORITHM_VERSION`'s docstring comment to note it is unchanged by ADR-0034 (no code change needed to the value itself — see Global Constraints):

```python
ALGORITHM_VERSION = "adr-0028-v1"
"""Unchanged by ADR-0034 -- that task only moves the source of the
requires_single_supplier boolean from a code constant (STRICT_CATEGORIES) to
a DB column; the ILP constraint model itself is mathematically identical, so
per ADR-0028's own bump rule this is not a new algorithm version. Was
"adr-0005-v1" before ADR-0028."""
```

- [ ] **Step 4: Run allocation test suite**

```
cd backend && python -m pytest tests/allocation/ -v
```
Expected: all tests in `test_service.py`, `test_override.py`, `test_solver.py`, `test_api.py` PASS.

- [ ] **Step 5: Add the new synchronization test**

```python
# backend/tests/allocation/test_service.py
def test_compute_split_categories_matches_solver_requires_single_supplier(
    db_session, make_supplier, make_material, make_category, make_price, make_project
):
    """ADR-0034 §3.1: both call sites (solver.py's materials_by_category and
    service.py's _compute_split_categories) must read
    Category.requires_single_supplier the same way. A category with the flag
    True and materials split across suppliers (via override) must produce a
    non-empty split_categories; a category with the flag False in the same
    shape must not."""
    from app.allocation.service import override_allocation_line_supplier

    session, *_ = db_session
    s1 = make_supplier(name="S1", flat_fee=0.0, free_shipping_threshold=0.0)
    s2 = make_supplier(name="S2", flat_fee=0.0, free_shipping_threshold=0.0)

    strict_cat = make_category(name="StrictCat", requires_single_supplier=True)
    strict_1 = make_material(category=strict_cat)
    strict_2 = make_material(category=strict_cat)
    make_price(strict_1, s1, price=5.00, availability=10)
    make_price(strict_2, s1, price=6.00, availability=10)
    make_price(strict_1, s2, price=7.00, availability=10)
    strict_project = make_project([(strict_1, 1), (strict_2, 1)])

    strict_run = run_allocation(session, strict_project.id)
    strict_line = (
        session.query(AllocationLine)
        .filter_by(allocation_run_id=strict_run.id, material_id=strict_1.id)
        .one()
    )
    override_allocation_line_supplier(session, strict_run.id, strict_line.id, s2.id)
    session.refresh(strict_run)
    assert strict_run.split_categories == ["StrictCat"]

    lax_cat = make_category(name="LaxCat", requires_single_supplier=False)
    lax_1 = make_material(category=lax_cat)
    lax_2 = make_material(category=lax_cat)
    make_price(lax_1, s1, price=5.00, availability=10)
    make_price(lax_2, s1, price=6.00, availability=10)
    make_price(lax_1, s2, price=7.00, availability=10)
    lax_project = make_project([(lax_1, 1), (lax_2, 1)])

    lax_run = run_allocation(session, lax_project.id)
    lax_line = (
        session.query(AllocationLine)
        .filter_by(allocation_run_id=lax_run.id, material_id=lax_1.id)
        .one()
    )
    override_allocation_line_supplier(session, lax_run.id, lax_line.id, s2.id)
    session.refresh(lax_run)
    assert lax_run.split_categories == []
```

Run:
```
cd backend && python -m pytest tests/allocation/test_service.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/allocation/service.py backend/tests/allocation/conftest.py backend/tests/allocation/test_service.py backend/tests/allocation/test_override.py
git commit -m "$(cat <<'EOF'
Rewrite _compute_split_categories on Category join, sync MaterialInput construction (ADR-0034 §3)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `price_ingestion/matching.py` — `category.name`, not `category!r`

**Files:**
- Modify: `backend/app/price_ingestion/matching.py`
- Modify: `backend/tests/price_ingestion/conftest.py` (add `category` support to `make_material`, add `make_category`)
- Modify: `backend/tests/price_ingestion/test_matching.py`

**Interfaces:**
- Consumes: `Material.category_ref` relationship (Task 1's temporary name — will become `Material.category` in Task 7 after the old String column is dropped; write this task against `category_ref` now, since Task 5 runs before Task 7's column drop. **Reconciliation note:** to avoid a second edit later, this task's code change targets whatever the current attribute name is at the time this task runs — since Task 7 (migration b) has not run yet when this task executes, use `category_ref` here, and Task 7 will need a one-line follow-up rename in this same file. Flag this explicitly in Task 7's step list.)

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/price_ingestion/conftest.py` a `make_category` fixture (same shape as Task 4's), and extend `make_material` to accept `category=None`:

```python
@pytest.fixture
def make_category(db_session):
    session, _material_ids, _supplier_ids, _user_ids = db_session

    def _make(name="Test Category", sku_prefix="TCAT", requires_single_supplier=False):
        from app.models import Category

        category = Category(name=name, sku_prefix=sku_prefix, requires_single_supplier=requires_single_supplier)
        session.add(category)
        session.flush()
        return category

    return _make


@pytest.fixture
def make_material(db_session):
    session, material_ids, _supplier_ids, _user_ids = db_session

    def _make(canonical_name=None, unit="ft", attributes=None, category=None):
        sku = f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            category_id=category.id if category is not None else None,
            unit=unit,
            attributes=attributes or {},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make
```

Add to `backend/tests/price_ingestion/test_matching.py`:

```python
def test_candidate_context_uses_category_name_not_repr(make_material, make_category):
    """Regression for ADR-0034 "Контекст" п.3: _candidate_context must render
    the human-readable Category.name in the LLM prompt, never repr() of the
    ORM object and never an AttributeError from the old String column being
    gone."""
    from app.price_ingestion.matching import _candidate_context

    doors = make_category(name="Doors", sku_prefix="DOOR")
    material = make_material(canonical_name="6ft Door Panel", category=doors)

    context = _candidate_context([material])

    assert "категория='Doors'" in context
    assert "Category object at" not in context
```

- [ ] **Step 2: Run to verify it fails**

```
cd backend && python -m pytest tests/price_ingestion/test_matching.py::test_candidate_context_uses_category_name_not_repr -v
```
Expected: FAIL — either `AttributeError` (if the old `category` String column already removed by the time this runs — not the case yet, this runs before Task 7) or an assertion failure showing the repr of an ORM object or `None` (since the fixture no longer sets a plain string). Given execution order (Task 5 runs before Task 7 drops the column), the actual observed failure will be the assertion on `"категория='Doors'"` not matching (current code reads `m.category` — the old String column — which is `None` for a material created via the new `category=` kwarg pointing at `category_id`).

- [ ] **Step 3: Update `_candidate_context`**

```python
def _candidate_context(candidates: list[Material]) -> str:
    lines = [
        f"- id={m.id}, sku={m.internal_sku!r}, название={m.canonical_name!r}, "
        f"категория={m.category_ref.name!r if m.category_ref else None!r}, единица={m.unit!r}"
        for m in candidates
    ]
    return "\n".join(lines) if lines else "(каталог пуст)"
```

The inline conditional inside an f-string above is invalid Python (a conditional expression needs full parenthesization) — write it correctly:

```python
def _candidate_context(candidates: list[Material]) -> str:
    lines = [
        f"- id={m.id}, sku={m.internal_sku!r}, название={m.canonical_name!r}, "
        f"категория={(m.category_ref.name if m.category_ref else None)!r}, единица={m.unit!r}"
        for m in candidates
    ]
    return "\n".join(lines) if lines else "(каталог пуст)"
```

- [ ] **Step 4: Run to verify it passes**

```
cd backend && python -m pytest tests/price_ingestion/test_matching.py -v
```
Expected: all PASS, including the new regression test and every pre-existing test in this file (none of which previously depended on `category` being set, per the earlier grep finding no `category` usage in this test file).

- [ ] **Step 5: Commit**

```bash
git add backend/app/price_ingestion/matching.py backend/tests/price_ingestion/conftest.py backend/tests/price_ingestion/test_matching.py
git commit -m "$(cat <<'EOF'
Fix _candidate_context to read Category.name via relationship, not repr() (ADR-0034 finding)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `api/template.py` — `category_name: str`, drop `category`

**Files:**
- Modify: `backend/app/api/schemas/template.py`
- Modify: `backend/app/api/template.py`
- Modify: `backend/tests/template/conftest.py`
- Modify: `backend/tests/template/test_api.py`

**Interfaces:**
- Produces: `ProjectTemplateItemOut.category_name: str` (non-nullable) — replaces `category: str | None`.

- [ ] **Step 1: Update `tests/template/conftest.py`'s `make_material` to require a category**

```python
@pytest.fixture
def make_category(db_session):
    session, *_ = db_session

    def _make(name="Test Category", sku_prefix="TCAT", requires_single_supplier=False):
        from app.models import Category

        category = Category(name=name, sku_prefix=sku_prefix, requires_single_supplier=requires_single_supplier)
        session.add(category)
        session.flush()
        return category

    return _make


@pytest.fixture
def make_material(db_session):
    session, material_ids, *_rest = db_session

    def _make(sku=None, canonical_name=None, category=None, unit="ft"):
        sku = sku or f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        if category is None:
            from app.models import Category

            category = Category(
                name=f"AutoCategory-{sku}", sku_prefix=f"AC{uuid.uuid4().hex[:6]}"
            )
            session.add(category)
            session.flush()
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            category_id=category.id,
            unit=unit,
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make
```

This keeps every existing call site in `test_api.py` working unchanged (they pass `category="fencing"` as a **string** today — Task 6 Step 2 below updates those call sites to pass a `Category` object via the new `make_category` fixture instead, since the fixture signature is changing from "string category" to "Category object").

- [ ] **Step 2: Update `test_api.py` call sites and assertions**

```python
def test_add_item_returns_template_with_denormalized_material_fields(
    db_session, make_template, make_material, make_category, make_user, make_session
):
    template = make_template()
    fencing = make_category(name="fencing", sku_prefix="FENC")
    material = make_material(canonical_name="6ft Vinyl Panel", unit="panel", category=fencing)
    client = _admin_client(make_user, make_session)

    response = client.post(
        f"/project-templates/{template.id}/items",
        json={"material_id": str(material.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["material_id"] == str(material.id)
    assert items[0]["canonical_name"] == "6ft Vinyl Panel"
    assert items[0]["unit"] == "panel"
    assert items[0]["category_name"] == "fencing"
```

All other `make_material(...)` calls in this file that don't pass `category=` are unaffected by the *string* rename — but note Step 1's `make_material` now auto-creates a `Category` row when none is passed, so `ProjectTemplateItemOut.category_name` is always populated, matching the new non-nullable schema. No other test in `test_api.py` asserts on `category`/`category_name`, so no further changes are needed there.

- [ ] **Step 3: Run to verify current-code failure state**

```
cd backend && python -m pytest tests/template/test_api.py -v
```
Expected: `test_add_item_returns_template_with_denormalized_material_fields` FAILS (`KeyError: 'category_name'`, since the response still has `category`); other tests should still pass structurally (they don't touch this field) but will fail to construct fixtures if `make_material`'s new default-category logic has bugs — check this run's full output.

- [ ] **Step 4: Update `ProjectTemplateItemOut` schema**

```python
# backend/app/api/schemas/template.py
class ProjectTemplateItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    material_id: uuid.UUID
    canonical_name: str
    unit: str
    category_name: str
```

- [ ] **Step 5: Update `_to_out` in `template.py`**

```python
def _to_out(template: ProjectTemplate) -> ProjectTemplateOut:
    return ProjectTemplateOut(
        id=template.id,
        name=template.name,
        created_at=template.created_at,
        items=[
            ProjectTemplateItemOut(
                id=item.id,
                material_id=item.material_id,
                canonical_name=item.material.canonical_name,
                unit=item.material.unit,
                category_name=item.material.category_ref.name,
            )
            for item in template.items
        ],
    )
```

Note: this reads `item.material.category_ref.name` — since `category_id` is still nullable at this point in the migration sequence (Task 7 makes it NOT NULL), this line would raise `AttributeError` on a `None` `category_ref` for any material without a category. Given the ADR's explicit requirement that `category_name` be non-nullable post-refactor, and that in practice all 294 real materials get a category via backfill before this code path is exercised against real data, this is acceptable — but the test fixture (Step 1) already guarantees every test material has a category, so no test will hit the `None` case. Document this ordering dependency inline:

```python
                # item.material.category_ref is guaranteed non-None once the
                # ADR-0034 backfill has run + migration (b) makes category_id
                # NOT NULL — until then this assumes every Material touched
                # by this endpoint already has a category (true for all test
                # fixtures and, after backfill, all real catalog rows).
                category_name=item.material.category_ref.name,
```

- [ ] **Step 6: Run to verify tests pass**

```
cd backend && python -m pytest tests/template/ -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/schemas/template.py backend/app/api/template.py backend/tests/template/conftest.py backend/tests/template/test_api.py
git commit -m "$(cat <<'EOF'
Rename ProjectTemplateItemOut.category to category_name, read via Category relationship (ADR-0034 finding)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Migration (b) — backfill on dev DB, NOT NULL, drop old column, rename relationship

**Files:**
- Create: `backend/alembic/versions/<hash>_category_id_not_null_drop_category.py`
- Modify: `backend/app/models/material.py` (rename `category_ref` → `category`)
- Modify: `backend/app/price_ingestion/matching.py` (rename `category_ref` → `category`, from Task 5)
- Modify: `backend/app/allocation/service.py` (rename `category_ref` → `category`, from Task 4)
- Modify: `backend/app/api/template.py` (rename `category_ref` → `category`, from Task 6)
- Modify: all test conftests that create `Material` — none need changes here since they use `category_id`/ORM kwargs, not `.category_ref` directly.

**Interfaces:** No new public interfaces — this task is a rename + finalize.

- [ ] **Step 1: Run the backfill dry-run against the dev DB (NOT --apply yet)**

```
cd backend && python -m app.scripts.backfill_material_categories
```

Capture and review the full report output. **STOP HERE and show the user the complete dry-run report before proceeding to Step 2.** Confirm:
- Exactly 8 categories reported.
- `{Doors, Gutter, Profil, Mesh, Roof panels}` → `requires_single_supplier=True`; `{Connectors, Screws, Caulk}` → `False`.
- No `unknown_categories`.
- Material counts sum to 294 (or whatever the current dev DB catalog size is).

- [ ] **Step 2: Wait for explicit user go-ahead, then run `--apply`**

```
cd backend && python -m app.scripts.backfill_material_categories --apply
```

Confirm the printed report shows `verification_ok` true and "Записано в БД: 8 категорий."

- [ ] **Step 3: Generate migration (b)**

```
cd backend && alembic revision -m "category_id not null, drop material category string column"
```

```python
"""category_id not null, drop material category string column

Revision ID: <generated>
Revises: <Task 1's migration revision>
Create Date: ...

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "<generated>"
down_revision: str | None = "<Task 1 migration>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("materials", "category_id", nullable=False)
    op.drop_column("materials", "category")


def downgrade() -> None:
    op.add_column("materials", sa.Column("category", sa.String(length=100), nullable=True))
    op.alter_column("materials", "category_id", nullable=True)
```

Note: `downgrade()` here cannot restore the original string *values* (they're gone) — only the column shape, matching the same lossy-downgrade precedent as `1d82548b7a2c`'s `created_by` column (which also only restores the column, not historical data). This is acceptable per that established precedent; do not attempt to reconstruct values from `Category.name` joins in the downgrade, since which category a given material *used to* belong to before any post-migration recategorization is not knowable from `category_id` alone in general — keep the downgrade simple and explicit about its limitation via a comment:

```python
def downgrade() -> None:
    # Lossy: restores the column shape only, not the original string values
    # (same precedent as migration 1d82548b7a2c's created_by column restore).
    op.add_column("materials", sa.Column("category", sa.String(length=100), nullable=True))
    op.alter_column("materials", "category_id", nullable=True)
```

- [ ] **Step 4: Run upgrade/downgrade/upgrade cycle on dev DB**

```
cd backend && alembic upgrade head
cd backend && alembic downgrade -1
cd backend && alembic upgrade head
```
Expected: all succeed. After the final `upgrade head`, confirm via `psql` or a quick script that `materials.category` no longer exists and `materials.category_id` is `NOT NULL`.

- [ ] **Step 5: Rename `category_ref` → `category` across the codebase**

In `backend/app/models/material.py`:
```python
    category: Mapped["Category"] = relationship(back_populates="materials")
```
(remove the "temporary name" docstring comment, remove the now-dead `category: Mapped[str | None] = mapped_column(String(100))` line entirely, remove the now-unused `String` import if nothing else in the file uses it — check before removing).

In `backend/app/models/category.py`, the back_populates target name (`materials`) does not change — only the `Material` side's attribute name changed, so no edit needed there beyond confirming `back_populates="materials"` still matches.

In `backend/app/price_ingestion/matching.py`:
```python
def _candidate_context(candidates: list[Material]) -> str:
    lines = [
        f"- id={m.id}, sku={m.internal_sku!r}, название={m.canonical_name!r}, "
        f"категория={(m.category.name if m.category else None)!r}, единица={m.unit!r}"
        for m in candidates
    ]
    return "\n".join(lines) if lines else "(каталог пуст)"
```
(Given `category_id` is now NOT NULL, `m.category` can no longer be `None` in practice — but keep the defensive `if m.category else None` for symmetry with any not-yet-backfilled test fixture that doesn't set one; simplify only if Task 5's test fixture is updated to always require a category — leave as-is here to avoid an unrelated behavior change.)

In `backend/app/allocation/service.py`:
```python
    materials = [
        MaterialInput(
            material_id=str(item.material_id),
            quantity=item.quantity,
            category_id=str(item.material.category_id),
            requires_single_supplier=item.material.category.requires_single_supplier,
            category_name=item.material.category.name,
        )
        for item in project_items
    ]
```
(simplify away the `if ... else` guards from Task 4 Step 3, since `category_id` is now guaranteed non-null).

In `backend/app/api/template.py`:
```python
                category_name=item.material.category.name,
```
(drop the ordering-dependency comment from Task 6 Step 5 — it's now unconditionally true).

- [ ] **Step 6: Run the full backend test suite**

```
cd backend && python -m pytest -v
```
Expected: all tests PASS. Investigate and fix any test fixture that still constructs a `Material` without a `category`/`category_id` (these will now violate the NOT NULL constraint at the DB level) — per the earlier fixture survey, `tests/project/conftest.py`'s `make_material` never set `category` at all; confirm whether any `project`-suite test actually needs a category (likely not, since `Project`/`ProjectItem` tests don't touch allocation) — if `category_id` is NOT NULL at the DB level, **every** `Material` insert across the whole test suite must supply one. Update `tests/project/conftest.py::make_material` the same way as Task 6 Step 1 (auto-create a throwaway `Category` when none passed):

```python
@pytest.fixture
def make_material(db_session):
    session, material_ids, _supplier_ids, _user_ids = db_session

    def _make(canonical_name=None, unit="ft", attributes=None):
        from app.models import Category

        sku = f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        category = Category(
            name=f"AutoCategory-{sku}", sku_prefix=f"AC{uuid.uuid4().hex[:6]}"
        )
        session.add(category)
        session.flush()
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            category_id=category.id,
            unit=unit,
            attributes=attributes or {},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make
```

Apply the same audit-and-fix pattern to `tests/material/conftest.py::make_material` (Task 8 will touch this fixture again for SKU autogen — coordinate so it isn't edited twice pointlessly; if Task 8 hasn't run yet, make the minimal fix here: auto-create a `Category` when `category=None` is passed, same pattern as above, keeping the existing `category=None` parameter name for now since Task 8 will decide its final shape).

Re-run:
```
cd backend && python -m pytest -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/ backend/app/models/material.py backend/app/price_ingestion/matching.py backend/app/allocation/service.py backend/app/api/template.py backend/tests/project/conftest.py backend/tests/material/conftest.py
git commit -m "$(cat <<'EOF'
Migration (b): category_id NOT NULL, drop Material.category string column (ADR-0034 п.1/п.2)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Atomic `internal_sku` autogeneration + `material.py`/schema changes

**Files:**
- Modify: `backend/app/api/schemas/material.py`
- Modify: `backend/app/api/material.py`
- Modify: `backend/tests/material/conftest.py`
- Modify: `backend/tests/material/test_api.py`

**Interfaces:**
- Produces: `MaterialCreate(canonical_name: str, category_id: uuid.UUID, unit: str, attributes: dict = {})` (no `internal_sku`, no `category` string).
- Produces: `MaterialUpdate(canonical_name: str | None, category_id: uuid.UUID | None, unit: str | None, attributes: dict | None)` (no `internal_sku`).
- Produces: `MaterialOut.category_name: str` (replaces `category: str | None`).

- [ ] **Step 1: Update `tests/material/conftest.py`**

```python
import uuid
import uuid as _uuid
from datetime import datetime, timezone

import pytest

from app.auth.constants import SESSION_IDLE_TTL
from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import Category, Material, User, UserSession


@pytest.fixture
def db_session():
    session = SessionLocal()
    material_ids: list = []
    user_ids: list = []
    category_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, material_ids, user_ids, category_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
        if material_ids:
            session.query(Material).filter(Material.id.in_(material_ids)).delete(
                synchronize_session=False
            )
        if category_ids:
            session.query(Category).filter(Category.id.in_(category_ids)).delete(
                synchronize_session=False
            )
        if user_ids:
            session.query(UserSession).filter(UserSession.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            session.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        session.commit()
        session.close()


@pytest.fixture
def make_user(db_session):
    session, _material_ids, user_ids, _category_ids = db_session

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


@pytest.fixture
def make_category(db_session):
    session, _material_ids, _user_ids, category_ids = db_session
    counter = {"n": 0}

    def _make(name=None, sku_prefix=None, requires_single_supplier=False, next_sku_number=1):
        counter["n"] += 1
        name = name or f"Test Category {counter['n']}"
        sku_prefix = sku_prefix or f"TC{counter['n']}"
        category = Category(
            name=name,
            sku_prefix=sku_prefix,
            requires_single_supplier=requires_single_supplier,
            next_sku_number=next_sku_number,
        )
        session.add(category)
        session.flush()
        category_ids.append(category.id)
        return category

    return _make


@pytest.fixture
def make_material(db_session):
    session, material_ids, _user_ids, category_ids = db_session

    def _make(sku=None, canonical_name=None, category=None, unit="ft", attributes=None):
        sku = sku or f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        if category is None:
            category = Category(
                name=f"AutoCategory-{sku}", sku_prefix=f"AC{uuid.uuid4().hex[:6]}"
            )
            session.add(category)
            session.flush()
            category_ids.append(category.id)
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            category_id=category.id,
            unit=unit,
            attributes=attributes or {},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make
```

- [ ] **Step 2: Rewrite `tests/material/test_api.py`'s creation/update tests for the new contract**

Replace the `internal_sku`-in-payload tests and `category` string assertions. Key rewrites (full file — every test touching `internal_sku`/`category` in the payload or response needs one of these changes; tests untouched by category/sku are left as-is):

```python
def test_create_material_returns_201_with_body(db_session, make_user, make_session, make_category):
    session, material_ids, _user_ids, _category_ids = db_session
    client = _admin_client(make_user, make_session)
    category = make_category(name="Fencing", sku_prefix="FENC")

    response = client.post(
        "/materials",
        json={
            "canonical_name": "6ft Vinyl Fence Panel",
            "category_id": str(category.id),
            "unit": "panel",
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))
    assert body["canonical_name"] == "6ft Vinyl Fence Panel"
    assert body["category_name"] == "Fencing"
    assert body["internal_sku"] == "FENC-001"
    assert body["attributes"] == {}


def test_create_material_returns_409_for_duplicate_category_sku_race_is_not_applicable(
    db_session, make_material, make_user, make_session
):
    # internal_sku is no longer client-supplied, so the old "duplicate sku"
    # 409 test no longer applies to POST -- covered instead by the atomic
    # counter tests below. This test id is intentionally retired.
    pass
```

Actually retire that placeholder cleanly rather than leaving a `pass`-only test (violates "no placeholders"). Delete `test_create_material_returns_409_for_duplicate_sku` entirely (its scenario — client-supplied duplicate `internal_sku` — can no longer occur, since `internal_sku` is server-generated) and do not replace it with a stub.

Continue rewriting the remaining tests that reference `category`/`internal_sku` in payload or assertions:

```python
def test_get_material_returns_created_material(
    db_session, make_material, make_category, make_user, make_session
):
    category = make_category()
    material = make_material(canonical_name="Get Me Material", category=category)
    client = _admin_client(make_user, make_session)

    response = client.get(f"/materials/{material.id}")

    assert response.status_code == 200
    assert response.json()["canonical_name"] == "Get Me Material"
```

```python
def test_update_material_changes_fields(db_session, make_material, make_user, make_session):
    material = make_material(canonical_name="Old Name")
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/materials/{material.id}",
        json={"canonical_name": "New Name", "unit": "ft"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["canonical_name"] == "New Name"


def test_update_material_returns_409_when_sku_collides(
    db_session, make_material, make_user, make_session
):
    # internal_sku can no longer be set via PUT payload -- this scenario no
    # longer applies. Retired without replacement (see also the retired
    # create-duplicate-sku test above).
```

Delete `test_update_material_returns_409_when_sku_collides` entirely (same reasoning — cannot be triggered through the API anymore since `internal_sku` isn't accepted in `MaterialUpdate`).

```python
def test_update_material_partial_payload_preserves_omitted_fields(
    db_session, make_material, make_category, make_user, make_session
):
    fencing = make_category(name="fencing")
    material = make_material(
        canonical_name="Kept Name", category=fencing, unit="panel", attributes={"gauge": "6"}
    )
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/materials/{material.id}",
        json={"canonical_name": "Renamed Only"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["canonical_name"] == "Renamed Only"
    assert body["internal_sku"] == material.internal_sku
    assert body["category_name"] == "fencing"
    assert body["unit"] == "panel"
    assert body["attributes"] == {"gauge": "6"}


def test_update_material_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/materials/{uuid.uuid4()}",
        json={"canonical_name": "X", "unit": "ft"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404
```

```python
def test_update_material_does_not_reembed_when_only_category_changes(
    db_session, make_material, make_category, make_user, make_session
):
    material = make_material(canonical_name="Stable Name")
    other_category = make_category(name="new-category")
    client = _admin_client(make_user, make_session)

    with patch("app.api.material.embed_text") as mock_embed:
        response = client.put(
            f"/materials/{material.id}",
            json={"category_id": str(other_category.id)},
            headers={"X-CSRF-Token": CSRF},
        )

    assert response.status_code == 200
    mock_embed.assert_not_called()
```

For every remaining test in the file that constructs a `MaterialCreate`-shaped JSON body with `"internal_sku": ...` (e.g. `test_create_material_embeds_synchronously`, `test_create_material_survives_embedding_api_failure`), drop the `internal_sku` key entirely and add `"category_id": str(category.id)` using a `make_category()` fixture call, e.g.:

```python
def test_create_material_embeds_synchronously(db_session, make_user, make_session, make_category):
    session, material_ids, _user_ids, _category_ids = db_session
    client = _admin_client(make_user, make_session)
    category = make_category()

    with patch(
        "app.api.material.embed_text", return_value=[0.2] * 1536
    ) as mock_embed:
        response = client.post(
            "/materials",
            json={
                "canonical_name": "Embeddable Material",
                "category_id": str(category.id),
                "unit": "ft",
            },
            headers={"X-CSRF-Token": CSRF},
        )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))
    mock_embed.assert_called_once()

    material_cls = __import__("app.models", fromlist=["Material"]).Material
    material = session.get(material_cls, uuid.UUID(body["id"]))
    assert material.embedding is not None
    assert len(material.embedding) == 1536
```

Apply the same `category_id` substitution to `test_create_material_survives_embedding_api_failure`.

- [ ] **Step 3: Add the new required tests**

```python
def test_create_material_without_category_id_returns_422(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/materials",
        json={"canonical_name": "No Category Material", "unit": "ft"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_create_material_ignores_internal_sku_in_payload_returns_422(
    make_user, make_session, make_category
):
    """ADR-0034 п.7 explicit choice: internal_sku is not accepted at all --
    Pydantic's default extra="ignore" would silently drop it, but this
    project chooses to make the removal visible via strict rejection. See
    MaterialCreate's model_config in schemas/material.py."""
    client = _admin_client(make_user, make_session)
    category = make_category()

    response = client.post(
        "/materials",
        json={
            "canonical_name": "Explicit SKU Attempt",
            "category_id": str(category.id),
            "unit": "ft",
            "internal_sku": "HACKED-001",
        },
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_create_material_generates_sku_from_category_prefix(
    db_session, make_user, make_session, make_category
):
    session, material_ids, _user_ids, _category_ids = db_session
    client = _admin_client(make_user, make_session)
    category = make_category(name="Doors", sku_prefix="DOOR")

    response = client.post(
        "/materials",
        json={"canonical_name": "Door One", "category_id": str(category.id), "unit": "ea"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))
    assert body["internal_sku"] == "DOOR-001"


def test_create_material_after_backfill_continues_existing_sku_sequence(
    db_session, make_user, make_session, make_category, make_material
):
    """ADR-0034 п.4, the exact numeric regression: a Category left at
    next_sku_number=27 (as backfill would set for a 26-material Doors
    category) must produce DOOR-027 next, not DOOR-026 (reusing the last
    occupied number) or DOOR-028 (an off-by-one skip)."""
    session, material_ids, _user_ids, _category_ids = db_session
    category = make_category(name="Doors", sku_prefix="DOOR", next_sku_number=27)
    make_material(sku="DOOR-026", category=category)
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/materials",
        json={"canonical_name": "Door Twenty Seven", "category_id": str(category.id), "unit": "ea"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))
    assert body["internal_sku"] == "DOOR-027"


def test_create_material_sequential_calls_produce_distinct_skus_no_collision(
    db_session, make_user, make_session, make_category
):
    """ADR-0034 п.4: concurrent creation must not collide. TestClient/SQLite-
    style in-process testing can't easily exercise true DB-level concurrent
    transactions, so this test uses two independent sessions committing in
    sequence against the same Category row to prove the atomic UPDATE...
    RETURNING counter advances correctly across separate transactions (the
    row-level lock behavior itself is exercised for real by Postgres; this
    test proves the *counter arithmetic* is race-safe in principle by
    confirming two back-to-back creates never repeat a number)."""
    session, material_ids, _user_ids, _category_ids = db_session
    category = make_category(name="RaceCat", sku_prefix="RACE")
    client = _admin_client(make_user, make_session)

    first = client.post(
        "/materials",
        json={"canonical_name": "Race One", "category_id": str(category.id), "unit": "ea"},
        headers={"X-CSRF-Token": CSRF},
    )
    second = client.post(
        "/materials",
        json={"canonical_name": "Race Two", "category_id": str(category.id), "unit": "ea"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    material_ids.append(uuid.UUID(first.json()["id"]))
    material_ids.append(uuid.UUID(second.json()["id"]))
    assert first.json()["internal_sku"] != second.json()["internal_sku"]
    assert {first.json()["internal_sku"], second.json()["internal_sku"]} == {
        "RACE-001",
        "RACE-002",
    }


def test_update_material_cannot_set_internal_sku(
    db_session, make_material, make_user, make_session
):
    material = make_material()
    original_sku = material.internal_sku
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/materials/{material.id}",
        json={"canonical_name": "Renamed", "internal_sku": "SHOULD-NOT-APPLY"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_update_material_can_reclassify_category_without_new_sku(
    db_session, make_material, make_category, make_user, make_session
):
    """ADR-0034 п.4: PATCH may change category_id (reclassification) but
    never touches internal_sku -- the SKU issued at creation persists
    regardless of later recategorization."""
    old_category = make_category(name="Old", sku_prefix="OLD")
    new_category = make_category(name="New", sku_prefix="NEW")
    material = make_material(sku="OLD-001", category=old_category)
    client = _admin_client(make_user, make_session)

    response = client.put(
        f"/materials/{material.id}",
        json={"category_id": str(new_category.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["internal_sku"] == "OLD-001"
    assert body["category_name"] == "New"
```

- [ ] **Step 4: Run to verify current-code failure state**

```
cd backend && python -m pytest tests/material/test_api.py -v
```
Expected: multiple failures (422 handling not implemented, `category_id`/`category_name` not recognized, SKU not autogenerated) — confirms tests are exercising unimplemented behavior.

- [ ] **Step 5: Update `MaterialCreate`/`MaterialUpdate`/`MaterialOut` schemas**

```python
# backend/app/api/schemas/material.py
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class MaterialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str
    category_id: uuid.UUID
    unit: str
    attributes: dict = {}


class MaterialUpdate(BaseModel):
    """Частичное обновление: поля, не переданные в payload, сохраняют текущее
    значение в БД, а не сбрасываются на дефолт — см. update_material.
    internal_sku исключён полностью — SKU выдаётся один раз при создании и
    не пересчитывается при последующей переклассификации, см. ADR-0034 п.4."""

    model_config = ConfigDict(extra="forbid")

    canonical_name: str | None = None
    category_id: uuid.UUID | None = None
    unit: str | None = None
    attributes: dict | None = None


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    internal_sku: str
    canonical_name: str
    category_name: str
    unit: str
    attributes: dict
    color_options: list[str] | None = None
    color_fragment: str | None = None
```

`extra="forbid"` is the explicit choice per ADR-0034 п.7 (test in Step 3 pins `422` for a client-supplied `internal_sku`) — this resolves the "решить самому" instruction from the task in favor of strict rejection over silent ignoring, on the reasoning that silently dropping a field a client explicitly sent hides a client-side bug (e.g. old frontend code still sending `internal_sku`) that `422` surfaces immediately.

Since `MaterialOut` needs `category_name` computed from the relationship and `from_attributes=True` reads attributes by name, either add a `@property` on the `Material` model or use a Pydantic field validator. Simplest, consistent with the ADR's "computed field over relationship" framing — add a `model_validator` or read via a Python property on the ORM model. Prefer the ORM property (keeps schema plain `from_attributes`):

Add to `backend/app/models/material.py` (after Task 7 has renamed the relationship to `category`):

```python
    @property
    def category_name(self) -> str:
        return self.category.name
```

Place this property definition right after the `category` relationship declaration in the model.

- [ ] **Step 6: Update `material.py` — atomic SKU generation in `create_material`, `category_id` handling in `update_material`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.material import MaterialCreate, MaterialOut, MaterialUpdate
from app.auth.dependencies import require_role
from app.core.database import get_db
from app.models import Category, Material
from app.price_ingestion.embeddings import EmbeddingError, embed_text, material_embedding_input

router = APIRouter(prefix="/materials", dependencies=[Depends(require_role("admin"))])


def _escape_ilike(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/search", response_model=list[MaterialOut])
def search_materials(
    q: str = Query(..., min_length=2), db: Session = Depends(get_db)
) -> list[Material]:
    return list(
        db.query(Material)
        .filter(Material.canonical_name.ilike(f"%{_escape_ilike(q)}%", escape="\\"))
        .order_by(Material.canonical_name)
        .limit(20)
        .all()
    )


def _generate_internal_sku(db: Session, category_id: uuid.UUID) -> str:
    """Atomic counter increment — see ADR-0034 п.4. UPDATE ... RETURNING is a
    single statement that both reads the current value and takes Postgres's
    row-level lock on this Category row, so two concurrent creates against
    the same category can never read the same next_sku_number: the second
    transaction blocks until the first commits or rolls back. Must run in
    the same transaction as the Material INSERT that follows (no commit
    between this call and db.add(material); db.commit() below)."""
    result = db.execute(
        update(Category)
        .where(Category.id == category_id)
        .values(next_sku_number=Category.next_sku_number + 1)
        .returning(Category.next_sku_number, Category.sku_prefix)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Category not found")
    new_number, prefix = row
    return f"{prefix}-{new_number - 1:03d}"


@router.post("", response_model=MaterialOut, status_code=201)
def create_material(payload: MaterialCreate, db: Session = Depends(get_db)) -> Material:
    internal_sku = _generate_internal_sku(db, payload.category_id)

    material = Material(
        internal_sku=internal_sku,
        canonical_name=payload.canonical_name,
        category_id=payload.category_id,
        unit=payload.unit,
        attributes=payload.attributes,
    )
    try:
        material.embedding = embed_text(
            material_embedding_input(payload.canonical_name, payload.attributes)
        )
    except EmbeddingError:
        material.embedding = None

    db.add(material)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Material with this internal_sku already exists"
        ) from exc
    db.refresh(material)
    return material


@router.get("", response_model=list[MaterialOut])
def list_materials(db: Session = Depends(get_db)) -> list[Material]:
    return list(db.query(Material).order_by(Material.canonical_name).all())


@router.get("/{material_id}", response_model=MaterialOut)
def get_material(material_id: uuid.UUID, db: Session = Depends(get_db)) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found")
    return material


@router.put("/{material_id}", response_model=MaterialOut)
def update_material(
    material_id: uuid.UUID, payload: MaterialUpdate, db: Session = Depends(get_db)
) -> Material:
    """PATCH-семантика: поля, отсутствующие в payload, не трогаются.
    category_id может меняться (переклассификация) без пересчёта internal_sku
    — см. ADR-0034 п.4."""
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found")

    fields = payload.model_dump(exclude_unset=True)
    text_changed = "canonical_name" in fields or "attributes" in fields

    for field_name, value in fields.items():
        setattr(material, field_name, value)

    if text_changed:
        try:
            material.embedding = embed_text(
                material_embedding_input(material.canonical_name, material.attributes)
            )
        except EmbeddingError:
            pass

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Material with this internal_sku already exists"
        ) from exc
    db.refresh(material)
    return material


@router.delete("/{material_id}", status_code=204)
def delete_material(material_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found")
    db.delete(material)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Material is referenced by other records"
        ) from exc
```

- [ ] **Step 7: Run to verify tests pass**

```
cd backend && python -m pytest tests/material/ -v
```
Expected: all PASS, including every new test from Step 3.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/schemas/material.py backend/app/api/material.py backend/app/models/material.py backend/tests/material/conftest.py backend/tests/material/test_api.py
git commit -m "$(cat <<'EOF'
Atomic internal_sku autogeneration via Category.next_sku_number, category_id in MaterialCreate/Update (ADR-0034 п.4/п.7)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: New admin-only `/categories` router

**Files:**
- Create: `backend/app/api/schemas/category.py`
- Create: `backend/app/api/category.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/category/__init__.py`
- Create: `backend/tests/category/conftest.py`
- Create: `backend/tests/category/test_api.py`

**Interfaces:**
- Produces: `GET/POST /categories`, `PATCH/DELETE /categories/{id}`, admin-only router mounted in `main.py`.

- [ ] **Step 1: Write schemas**

```python
# backend/app/api/schemas/category.py
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    sku_prefix: str
    requires_single_supplier: bool = False


class CategoryUpdate(BaseModel):
    """sku_prefix отсутствует намеренно — неизменяем после создания, см.
    ADR-0034 п.5. Не просто игнорируется: поле физически отсутствует в схеме."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    requires_single_supplier: bool | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    sku_prefix: str
    requires_single_supplier: bool
    next_sku_number: int
    created_at: datetime
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/category/__init__.py
```
(empty, matches the `tests/scripts/__init__.py` convention)

```python
# backend/tests/category/conftest.py
import uuid
import uuid as _uuid
from datetime import datetime, timezone

import pytest

from app.auth.constants import SESSION_IDLE_TTL
from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import Category, Material, User, UserSession


@pytest.fixture
def db_session():
    session = SessionLocal()
    category_ids: list = []
    material_ids: list = []
    user_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, category_ids, material_ids, user_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
        if material_ids:
            session.query(Material).filter(Material.id.in_(material_ids)).delete(
                synchronize_session=False
            )
        if category_ids:
            session.query(Category).filter(Category.id.in_(category_ids)).delete(
                synchronize_session=False
            )
        if user_ids:
            session.query(UserSession).filter(UserSession.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            session.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        session.commit()
        session.close()


@pytest.fixture
def make_user(db_session):
    session, _category_ids, _material_ids, user_ids = db_session

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


@pytest.fixture
def make_category(db_session):
    session, category_ids, _material_ids, _user_ids = db_session
    counter = {"n": 0}

    def _make(name=None, sku_prefix=None, requires_single_supplier=False):
        counter["n"] += 1
        name = name or f"Test Category {counter['n']}"
        sku_prefix = sku_prefix or f"TC{counter['n']}"
        category = Category(
            name=name, sku_prefix=sku_prefix, requires_single_supplier=requires_single_supplier
        )
        session.add(category)
        session.flush()
        category_ids.append(category.id)
        return category

    return _make


@pytest.fixture
def make_material(db_session):
    session, _category_ids, material_ids, _user_ids = db_session

    def _make(category, sku=None):
        sku = sku or f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        material = Material(
            internal_sku=sku, canonical_name=sku, category_id=category.id, unit="ft"
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make
```

```python
# backend/tests/category/test_api.py
import uuid

from fastapi.testclient import TestClient

from app.main import app

CSRF = "test-csrf-token"


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


_admin_email_counter = [0]


def _admin_client(make_user, make_session):
    _admin_email_counter[0] += 1
    email = f"admin-category{_admin_email_counter[0]}@screen-factory-florida.com"
    admin = make_user(email=email, role="admin")
    admin_session = make_session(admin, csrf_token=CSRF)
    return _client_as(admin_session)


# --- admin-only ---


def test_list_categories_no_session_returns_401():
    client = TestClient(app)
    response = client.get("/categories")
    assert response.status_code == 401


def test_list_categories_as_employee_returns_403(make_user, make_session):
    employee = make_user(role="employee")
    employee_session = make_session(employee)
    response = _client_as(employee_session).get("/categories")
    assert response.status_code == 403


def test_create_category_as_employee_returns_403(make_user, make_session):
    employee = make_user(email="employee-create@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    response = _client_as(employee_session).post(
        "/categories",
        json={"name": "X", "sku_prefix": "XX"},
        headers={"X-CSRF-Token": CSRF},
    )
    assert response.status_code == 403


def test_patch_category_as_employee_returns_403(make_category, make_user, make_session):
    category = make_category()
    employee = make_user(email="employee-patch@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    response = _client_as(employee_session).patch(
        f"/categories/{category.id}", json={"name": "Y"}, headers={"X-CSRF-Token": CSRF}
    )
    assert response.status_code == 403


def test_delete_category_as_employee_returns_403(make_category, make_user, make_session):
    category = make_category()
    employee = make_user(email="employee-delete@screen-factory-florida.com", role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    response = _client_as(employee_session).delete(
        f"/categories/{category.id}", headers={"X-CSRF-Token": CSRF}
    )
    assert response.status_code == 403


# --- CRUD ---


def test_create_category_returns_201(db_session, make_user, make_session):
    session, category_ids, _material_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/categories",
        json={"name": "Doors", "sku_prefix": "DOOR", "requires_single_supplier": True},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    category_ids.append(uuid.UUID(body["id"]))
    assert body["name"] == "Doors"
    assert body["sku_prefix"] == "DOOR"
    assert body["requires_single_supplier"] is True
    assert body["next_sku_number"] == 1


def test_create_category_defaults_requires_single_supplier_false(
    db_session, make_user, make_session
):
    session, category_ids, _material_ids, _user_ids = db_session
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/categories", json={"name": "Misc", "sku_prefix": "MISC"}, headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 201
    body = response.json()
    category_ids.append(uuid.UUID(body["id"]))
    assert body["requires_single_supplier"] is False


def test_create_category_returns_409_for_duplicate_name(
    db_session, make_category, make_user, make_session
):
    category = make_category(name="Doors")
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/categories",
        json={"name": category.name, "sku_prefix": "OTHER"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409


def test_create_category_returns_409_for_duplicate_sku_prefix(
    db_session, make_category, make_user, make_session
):
    category = make_category(sku_prefix="DUPE")
    client = _admin_client(make_user, make_session)

    response = client.post(
        "/categories",
        json={"name": "Different Name", "sku_prefix": category.sku_prefix},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 409


def test_patch_category_renames(db_session, make_category, make_user, make_session):
    category = make_category(name="Old Name")
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/categories/{category.id}", json={"name": "New Name"}, headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


def test_patch_category_toggles_requires_single_supplier(
    db_session, make_category, make_user, make_session
):
    category = make_category(requires_single_supplier=False)
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/categories/{category.id}",
        json={"requires_single_supplier": True},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200
    assert response.json()["requires_single_supplier"] is True


def test_patch_category_rejects_sku_prefix_field(
    db_session, make_category, make_user, make_session
):
    """ADR-0034 п.5: sku_prefix is immutable -- CategoryUpdate has no field
    for it at all, so a client attempting to send it gets a hard validation
    error, not silent ignoring."""
    category = make_category(sku_prefix="ORIG")
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/categories/{category.id}",
        json={"sku_prefix": "HACKED"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_patch_category_returns_409_for_duplicate_name(
    db_session, make_category, make_user, make_session
):
    make_category(name="Existing")
    other = make_category(name="Other")
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/categories/{other.id}", json={"name": "Existing"}, headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 409


def test_patch_category_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.patch(
        f"/categories/{uuid.uuid4()}", json={"name": "X"}, headers={"X-CSRF-Token": CSRF}
    )

    assert response.status_code == 404


def test_delete_empty_category_returns_204(db_session, make_category, make_user, make_session):
    session, category_ids, _material_ids, _user_ids = db_session
    category = make_category()
    category_ids.remove(category.id)
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/categories/{category.id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 204


def test_delete_category_with_materials_returns_409_with_count(
    db_session, make_category, make_material, make_user, make_session
):
    category = make_category(name="Doors")
    make_material(category)
    make_material(category)
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/categories/{category.id}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 409
    assert "2" in response.json()["detail"]


def test_delete_category_returns_404_for_unknown_id(make_user, make_session):
    client = _admin_client(make_user, make_session)

    response = client.delete(f"/categories/{uuid.uuid4()}", headers={"X-CSRF-Token": CSRF})

    assert response.status_code == 404


def test_list_categories_includes_created_category(
    db_session, make_category, make_user, make_session
):
    category = make_category(name="Listed Category")
    client = _admin_client(make_user, make_session)

    response = client.get("/categories")

    assert response.status_code == 200
    names = [row["name"] for row in response.json()]
    assert "Listed Category" in names
```

- [ ] **Step 3: Run to verify failure (module doesn't exist)**

```
cd backend && python -m pytest tests/category/ -v
```
Expected: import/collection errors or 404s (router not mounted).

- [ ] **Step 4: Implement `app/api/category.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas.category import CategoryCreate, CategoryOut, CategoryUpdate
from app.auth.dependencies import require_role
from app.core.database import get_db
from app.models import Category, Material

router = APIRouter(prefix="/categories", dependencies=[Depends(require_role("admin"))])


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[Category]:
    return list(db.query(Category).order_by(Category.name).all())


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)) -> Category:
    category = Category(
        name=payload.name,
        sku_prefix=payload.sku_prefix,
        requires_single_supplier=payload.requires_single_supplier,
    )
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Category with this name or sku_prefix already exists"
        ) from exc
    db.refresh(category)
    return category


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: uuid.UUID, payload: CategoryUpdate, db: Session = Depends(get_db)
) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    fields = payload.model_dump(exclude_unset=True)
    for field_name, value in fields.items():
        setattr(category, field_name, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Category with this name already exists"
        ) from exc
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    material_count = db.query(Material).filter(Material.category_id == category_id).count()
    if material_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Category is referenced by {material_count} material(s), cannot delete",
        )

    db.delete(category)
    db.commit()
```

- [ ] **Step 5: Register the router in `main.py`**

```python
from app.api.allocation import router as allocation_router
from app.api.auth import router as auth_router
from app.api.category import router as category_router
from app.api.health import router as health_router
from app.api.material import router as material_router
from app.api.order import router as order_router
from app.api.price import router as price_router
from app.api.price_ingestion import router as price_ingestion_router
from app.api.project import router as project_router
from app.api.purchase_record import router as purchase_record_router
from app.api.supplier import router as supplier_router
from app.api.template import router as template_router
from app.api.user import router as user_router
```

```python
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(project_router)
app.include_router(allocation_router)
app.include_router(order_router)
app.include_router(purchase_record_router)
app.include_router(template_router)
app.include_router(supplier_router)
app.include_router(material_router)
app.include_router(category_router)
app.include_router(price_router)
app.include_router(price_ingestion_router)
```

- [ ] **Step 6: Run to verify tests pass**

```
cd backend && python -m pytest tests/category/ -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/schemas/category.py backend/app/api/category.py backend/app/main.py backend/tests/category/
git commit -m "$(cat <<'EOF'
Add admin-only /categories CRUD router (ADR-0034 п.5/п.6)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Full regression pass, ruff, real-catalog dry-run, docs update

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/data-model.md`
- No new code files.

**Interfaces:** N/A — verification and documentation task.

- [ ] **Step 1: Run the full backend test suite**

```
cd backend && python -m pytest -v
```
Expected: 100% pass. If any test outside the ones touched in Tasks 1–9 fails (e.g. `tests/allocation/test_api.py`, `tests/scripts/test_xlsx_price_matrix.py`, `tests/scripts/test_bootstrap_admin.py`), investigate — `test_xlsx_price_matrix.py` should be unaffected (that module's own parsing logic wasn't touched, only consumed by the backfill script), but confirm no fixture elsewhere still constructs a `Material` with a bare `category=` string kwarg that the DB no longer accepts.

- [ ] **Step 2: Run ruff**

```
cd backend && ruff check .
```
Expected: no errors. Fix any lint issues found (unused imports like the removed `String` in `material.py` if missed, line length, etc.) and re-run.

- [ ] **Step 3: Run the real-catalog dry-run backfill one more time to confirm no drift since Task 7**

```
cd backend && python -m app.scripts.backfill_material_categories
```

If Task 7 already applied the backfill to the dev DB, this should now report **zero** categories to create (all 294 materials already have `category_id` set, and the old `category` String column no longer exists after Task 7's migration (b) — so at this point the script's `SELECT DISTINCT category` query would fail with a column-does-not-exist error). **This is expected and correct**: `backfill_material_categories.py` is a one-time script whose job is done once migration (b) has run; running it again post-migration is not a supported operation. Confirm this explicitly rather than treating a failure here as a regression — do not modify the script to handle the post-drop case, since ADR-0034 scopes it as a one-time backfill only.

- [ ] **Step 4: Update `docs/data-model.md`**

Add the `Category` entity to the ER diagram and table descriptions: fields (`id`, `name`, `sku_prefix`, `requires_single_supplier`, `next_sku_number`, `created_at`), the `Material.category_id -> Category.id` FK relationship, and a note that `Material.category` (String) no longer exists (superseded by ADR-0034). Read the current file first to match its existing Mermaid syntax and section structure before editing.

- [ ] **Step 5: Update `docs/architecture.md`**

Add a note wherever `STRICT_CATEGORIES` or `Material.category` is currently mentioned (if at all) that the strictness flag now lives on `Category.requires_single_supplier`, managed via the new `/categories` admin CRUD, per ADR-0034. Read the current file first.

- [ ] **Step 6: Commit**

```bash
git add docs/architecture.md docs/data-model.md
git commit -m "$(cat <<'EOF'
Update architecture/data-model docs for Category entity (ADR-0034)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Report final status to the user**

Present: full `pytest -v` output summary (pass count), `ruff check .` output (clean), confirmation that both migrations' upgrade/downgrade/upgrade cycles were run successfully on the dev DB (from Tasks 1 and 7), and the full dry-run backfill report captured in Task 7 Step 1 (294-material real catalog). Explicitly state that `--apply` was run only after the user's confirmation in Task 7 Step 2, per the "жду подтверждения перед --apply" instruction.

---

## Self-Review Notes (for the plan author, not a task)

- Every ADR-0034 numbered requirement (1–8 in the task prompt) maps to a task: (1) migrations → Tasks 1 & 7; (2) backfill script → Task 2; (3) solver.py → Task 3; (4) service.py → Task 4; (5) matching.py → Task 5; (6) template.py → Task 6; (7) internal_sku autogen → Task 8; (8) /categories router → Task 9.
- All required tests from the task's "Тесты" list are covered: 9 rewritten ADR-0028 solver tests (Task 3), 2 deleted constant tests replaced by backfill test (Task 2 + Task 3), `_compute_split_categories` sync test (Task 4), default-`False` non-grouping test (Task 3 Step 6), backfill dry-run/--apply/verification/error tests (Task 2), exact `DOOR-027` SKU test (Task 8), parallel-creation test (Task 8), admin-only 403 tests (Task 9), POST/PATCH uniqueness + PATCH-rejects-sku_prefix tests (Task 9), DELETE 409/204 tests (Task 9), matching.py regression (Task 5), template.py regression (Task 6), internal_sku-in-POST-body explicit-422 choice (Task 8).
- The `category_ref` → `category` intermediate relationship name (Tasks 1–6) followed by the final rename (Task 7) is a deliberate sequencing choice to avoid ever having the ORM relationship and the not-yet-dropped String column collide on the same attribute name — flagged explicitly in Task 1 and revisited in Task 7 Step 5 with the exact list of files needing the rename.
