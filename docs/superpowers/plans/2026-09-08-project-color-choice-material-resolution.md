# Project color_choice & material name resolution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend-only support for a single project-wide color choice that
resolves ambiguous two-color material names (`"(White/Bronze)"` or bare
`"Bronze/White"`) into one supplier-facing color, and blocks Order creation
until that choice is made when the project's plan needs it.

**Architecture:** Two new nullable columns on `Material`
(`color_options: list[str] | None` JSON, `color_fragment: str | None`) plus
one on `Project` (`color_choice: str | None`), populated once by a
dry-run/`--apply` backfill script for the existing 294-row catalog and by
extending the xlsx import parser for future imports. A single pure function
`resolve_material_name(material, color)` centralizes the string
substitution so no caller re-parses `canonical_name`. `create_orders_for_run`
gains a pre-creation guard that raises a new exception (mapped to a 409) when
the plan contains a material with non-empty `color_options` and
`Project.color_choice IS NULL`. `PATCH /projects/{id}` gains an optional
`color_choice` field, validated against the same known-colors dictionary.

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic, pytest, ruff. Backend only.

**Spec:** `docs/decisions/0031-project-color-choice-and-material-name-resolution.md`
(full ADR — follow it exactly, including both color-parsing formats found in
Step 0 and the color_options/color_fragment split). Also load-bearing:
`docs/decisions/0027-order-item-target-price-and-second-negotiation-round.md`
§5 (buildOrderText/buildTargetPriceOrderText — frontend wiring is explicitly
out of scope for this task, but the backend function must be ready for it)
and `docs/decisions/0007-order-price-confirmation.md` §2, §6 (Order creation
is the blocking point; `/orders/:id/print` doesn't exist yet and is not
built here).

## Global Constraints

- Backend only — no frontend changes in this plan (ADR-0031 explicitly
  defers `OrderDetailPage.tsx`/`ProjectDetailPage.tsx`/
  `AllocationResultPage.tsx` wiring to a separate task).
- Known-colors dictionary is a fixed constant (`WHITE`, `BRONZE` today), not
  a dynamically inferred set — a typo like `Bronz` must never silently
  create a third "color".
- `color_options` is a JSON array of normalized strings in canonical_name
  order (`["White", "Bronze"]`), not a set.
- Single-color parenthetical (`"(White)"`) never produces `color_options` —
  deliberate, not an oversight.
- Migration adds nullable columns with no backfill inside the migration
  itself — backfill is the separate script.
- `resolve_material_name` does not decide whether to block generation — that
  is `create_orders_for_run`'s job (ADR-0031 п.4 "calling contract").
- Do not run `--apply` on the backfill script without the user's explicit
  go-ahead after reviewing the dry-run output.
- Do not touch `docs/ui-reference.md` (already modified by a parallel
  frontend-prep pass per git status) or any frontend file.

---

## File Structure

- `backend/alembic/versions/<new>_add_color_fields.py` — migration: adds
  `materials.color_options` (JSON, nullable), `materials.color_fragment`
  (VARCHAR(50), nullable), `projects.color_choice` (VARCHAR(20), nullable).
- `backend/app/models/material.py` — add `color_options`, `color_fragment`
  columns.
- `backend/app/models/project.py` — add `color_choice` column.
- `backend/app/services/material_naming.py` — new module: known-colors
  dictionary, the two regexes, a shared `parse_color(text) -> ColorParseResult
  | None` helper (used by both the backfill script and the xlsx importer so
  the parsing logic exists in exactly one place), and `resolve_material_name`.
- `backend/app/scripts/backfill_color_options.py` — new one-time script,
  dry-run default / `--apply` flag, reusing `material_naming.parse_color`.
- `backend/app/scripts/xlsx_price_matrix.py` — `MaterialRow` gains
  `color_options`/`color_fragment` fields, populated during parsing via
  `material_naming.parse_color`.
- `backend/app/scripts/import_real_data.py` — `create_materials` copies the
  new fields from `MaterialRow` onto the created `Material`.
- `backend/app/allocation/order_service.py` — new
  `ProjectColorChoiceRequiredError` exception; `create_orders_for_run` gains
  the guard.
- `backend/app/api/order.py` — catches the new exception, returns 409.
- `backend/app/api/schemas/project.py` — `ProjectUpdate` gains optional
  `color_choice: str | None = Field(default=None)`; `ProjectOut` exposes
  `color_choice`.
- `backend/app/api/project.py` — `update_project` writes `color_choice` when
  present in `model_fields_set` (independently optional, same `_UNSET`-style
  pattern already used elsewhere — but since `ProjectUpdate` today has only
  `title` as required, this task makes `title` handling stay as-is and adds
  `color_choice` as an independently-settable optional field).
- Tests:
  - `backend/tests/services/test_material_naming.py` (new) — parsing +
    `resolve_material_name` branches.
  - `backend/tests/scripts/test_backfill_color_options.py` (new).
  - `backend/tests/allocation/test_order_color_choice.py` (new) —
    `create_orders_for_run` guard.
  - `backend/tests/project/test_api.py` (extend) — PATCH `color_choice`.
  - `backend/tests/scripts/test_xlsx_price_matrix.py` (new or extend if it
    exists — check first) — parser populates color fields.

---

## Task 1: `material_naming` module — color parsing + `resolve_material_name`

**Files:**
- Create: `backend/app/services/material_naming.py`
- Test: `backend/tests/services/test_material_naming.py`

**Interfaces:**
- Produces:
  - `KNOWN_COLORS: frozenset[str]` = `{"WHITE", "BRONZE"}` (uppercase keys
    for lookup; canonical display form is title-case, e.g. `"White"`).
  - `@dataclass(frozen=True) class ColorParseResult: color_options: list[str]; color_fragment: str; pattern: Literal["parenthetical", "bare"]`
  - `def parse_color(canonical_name: str) -> ColorParseResult | None` — tries
    parenthetical regex first, then bare regex; returns `None` if neither
    matches confidently (including the "single color in parens" case, which
    is a confident non-match, not an error).
  - `def resolve_material_name(material: Material, color: str | None) -> str`
    — the four branches from ADR-0031 §4.

- [ ] **Step 1: Write failing tests for `parse_color`**

```python
# backend/tests/services/test_material_naming.py
import logging

import pytest

from app.services.material_naming import ColorParseResult, parse_color, resolve_material_name


def test_parse_color_parenthetical_two_colors():
    result = parse_color('Super Gutter End Cap 5" (White/Bronze)')
    assert result == ColorParseResult(
        color_options=["White", "Bronze"],
        color_fragment="(White/Bronze)",
        pattern="parenthetical",
    )


def test_parse_color_parenthetical_reverse_order_preserved():
    result = parse_color('Door Blank with 8” Kick Plate (Bronze/White)')
    assert result.color_options == ["Bronze", "White"]
    assert result.color_fragment == "(Bronze/White)"


def test_parse_color_bare_screws_format():
    result = parse_color('12 x 3/4" Bronze/White Stainless steel')
    assert result == ColorParseResult(
        color_options=["Bronze", "White"],
        color_fragment="Bronze/White",
        pattern="bare",
    )


def test_parse_color_bare_white_bronze_order():
    result = parse_color('10 x 3/4" White/Bronze Galvanized')
    assert result.color_options == ["White", "Bronze"]
    assert result.color_fragment == "White/Bronze"


def test_parse_color_single_color_in_parens_returns_none():
    result = parse_color("E-Fascia x 24’ (White)")
    assert result is None


def test_parse_color_no_color_word_returns_none():
    result = parse_color('3" Panel WITHOUT Fan Beam (.024)')
    assert result is None


def test_parse_color_no_color_at_all_returns_none():
    result = parse_color("Generic Bracket 4in")
    assert result is None


def test_parse_color_unknown_color_word_in_parens_not_matched():
    # "Bronz" is a typo, not a known color — must not silently match.
    result = parse_color("Widget (Bronz/White)")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/services/test_material_naming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.material_naming'`

- [ ] **Step 3: Implement `parse_color`**

```python
# backend/app/services/material_naming.py
"""Color parsing and supplier-facing name resolution for two-color
materials — see ADR-0031. Two literal formats exist in the real catalog,
both handled here and nowhere else (import_real_data.py/xlsx_price_matrix.py
and backfill_color_options.py both call parse_color; OrderDetailPage's
buildOrderText/buildTargetPriceOrderText and the future /orders/:id/print
call resolve_material_name — see ADR-0031 §5 for the full list)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.models.material import Material

logger = logging.getLogger(__name__)

KNOWN_COLORS: frozenset[str] = frozenset({"WHITE", "BRONZE"})
"""Fixed dictionary, not inferred from arbitrary text — a typo like "Bronz"
must never silently create a third color. Extend by adding an entry here
when a new color appears in a future price list (ADR-0031 п.1)."""

_PARENTHETICAL_RE = re.compile(r"\(([A-Za-z]+(?:/[A-Za-z]+)+)\)")
_BARE_RE = re.compile(
    r"\b([A-Za-z]+)/([A-Za-z]+)\b"
)


@dataclass(frozen=True)
class ColorParseResult:
    color_options: list[str]
    """Normalized, title-case, in canonical_name order — e.g. ["White",
    "Bronze"], not a set. See ADR-0031 п.1."""
    color_fragment: str
    """Exact substring in canonical_name to replace — includes the
    parentheses for the parenthetical format, bare text otherwise."""
    pattern: Literal["parenthetical", "bare"]


def _normalize_tokens(tokens: list[str]) -> list[str] | None:
    normalized = []
    for token in tokens:
        if token.upper() not in KNOWN_COLORS:
            return None
        normalized.append(token.capitalize())
    return normalized


def parse_color(canonical_name: str) -> ColorParseResult | None:
    """Returns None for: no color found, a single color in parentheses
    (deliberate non-match, ADR-0031 п.1 "Примечание про однoцветные
    материалы"), or a color-shaped token whose word(s) are not in
    KNOWN_COLORS (e.g. a typo). Tries the parenthetical format first, then
    the bare (no-parens) format used by the Screws category."""
    paren_match = _PARENTHETICAL_RE.search(canonical_name)
    if paren_match:
        tokens = paren_match.group(1).split("/")
        if len(tokens) < 2:
            return None
        normalized = _normalize_tokens(tokens)
        if normalized is None:
            return None
        return ColorParseResult(
            color_options=normalized,
            color_fragment=paren_match.group(0),
            pattern="parenthetical",
        )

    for bare_match in _BARE_RE.finditer(canonical_name):
        first, second = bare_match.group(1), bare_match.group(2)
        normalized = _normalize_tokens([first, second])
        if normalized is not None:
            return ColorParseResult(
                color_options=normalized,
                color_fragment=bare_match.group(0),
                pattern="bare",
            )

    return None
```

- [ ] **Step 4: Run test to verify parsing passes**

Run: `cd backend && pytest tests/services/test_material_naming.py -v -k parse_color`
Expected: PASS (9 tests)

- [ ] **Step 5: Write failing tests for `resolve_material_name`**

Append to the same test file:

```python
class _FakeMaterial:
    """Minimal stand-in for app.models.material.Material — resolve_material_name
    only reads canonical_name/color_options/color_fragment, so a real ORM
    instance is unnecessary here."""

    def __init__(self, canonical_name, color_options=None, color_fragment=None):
        self.canonical_name = canonical_name
        self.color_options = color_options
        self.color_fragment = color_fragment


def test_resolve_material_name_no_color_options_returns_as_is():
    material = _FakeMaterial("E-Fascia x 24’ (White)")
    assert resolve_material_name(material, None) == "E-Fascia x 24’ (White)"
    assert resolve_material_name(material, "White") == "E-Fascia x 24’ (White)"


def test_resolve_material_name_options_present_color_none_returns_as_is():
    material = _FakeMaterial(
        'Super Gutter End Cap 5" (White/Bronze)',
        color_options=["White", "Bronze"],
        color_fragment="(White/Bronze)",
    )
    assert resolve_material_name(material, None) == 'Super Gutter End Cap 5" (White/Bronze)'


def test_resolve_material_name_options_present_color_valid_parenthetical():
    material = _FakeMaterial(
        'Super Gutter End Cap 5" (White/Bronze)',
        color_options=["White", "Bronze"],
        color_fragment="(White/Bronze)",
    )
    assert resolve_material_name(material, "White") == 'Super Gutter End Cap 5" (White)'
    assert resolve_material_name(material, "Bronze") == 'Super Gutter End Cap 5" (Bronze)'


def test_resolve_material_name_options_present_color_valid_bare():
    material = _FakeMaterial(
        '12 x 3/4" Bronze/White Stainless steel',
        color_options=["Bronze", "White"],
        color_fragment="Bronze/White",
    )
    assert resolve_material_name(material, "White") == '12 x 3/4" White Stainless steel'
    assert resolve_material_name(material, "Bronze") == '12 x 3/4" Bronze Stainless steel'


def test_resolve_material_name_color_not_in_options_returns_as_is_and_logs(caplog):
    material = _FakeMaterial(
        'Super Gutter End Cap 5" (White/Bronze)',
        color_options=["White", "Bronze"],
        color_fragment="(White/Bronze)",
    )
    with caplog.at_level(logging.WARNING):
        result = resolve_material_name(material, "Green")
    assert result == 'Super Gutter End Cap 5" (White/Bronze)'
    assert "Green" in caplog.text
```

- [ ] **Step 6: Run to verify these fail**

Run: `cd backend && pytest tests/services/test_material_naming.py -v -k resolve_material_name`
Expected: FAIL — `AttributeError`/`ImportError: cannot import name 'resolve_material_name'`

- [ ] **Step 7: Implement `resolve_material_name`**

Append to `backend/app/services/material_naming.py`:

```python
def resolve_material_name(material: "Material", color: str | None) -> str:
    """Supplier-facing material name with the color ambiguity resolved —
    see ADR-0031 п.4. Pure function: does not decide whether generation
    should be blocked when color is None and color_options is non-empty —
    that is create_orders_for_run's job (ADR-0031 п.4 "calling contract").

    - color_options empty/None -> canonical_name as-is.
    - color_options non-empty, color is None -> canonical_name as-is (the
      caller is responsible for having already blocked this path if it
      shouldn't be reachable).
    - color_options non-empty, color present in color_options ->
      canonical_name with color_fragment replaced by the bare chosen color
      (parens stripped for the parenthetical format).
    - color present but not in color_options -> canonical_name as-is,
      logged as an anomaly (should not happen by construction, since
      Project.color_choice is restricted to the same KNOWN_COLORS
      dictionary, but this function must not crash or invent a color).
    """
    if not material.color_options:
        return material.canonical_name

    if color is None:
        return material.canonical_name

    if color not in material.color_options:
        logger.warning(
            "resolve_material_name: color %r not in color_options %r for material %r",
            color,
            material.color_options,
            material.canonical_name,
        )
        return material.canonical_name

    return material.canonical_name.replace(material.color_fragment, color)
```

- [ ] **Step 8: Run full test file**

Run: `cd backend && pytest tests/services/test_material_naming.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Ruff check**

Run: `cd backend && ruff check app/services/material_naming.py tests/services/test_material_naming.py`
Expected: no errors

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/material_naming.py backend/tests/services/test_material_naming.py
git commit -m "$(cat <<'EOF'
Add color parsing and resolve_material_name (ADR-0031 п.1/п.4)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Migration + model fields

**Files:**
- Modify: `backend/app/models/material.py`
- Modify: `backend/app/models/project.py`
- Create: `backend/alembic/versions/<hash>_add_color_fields.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Material.color_options: list[str] | None`,
  `Material.color_fragment: str | None`, `Project.color_choice: str | None` —
  used by Task 1's `resolve_material_name` (already written against these
  attribute names) and every later task.

- [ ] **Step 1: Add columns to `Material`**

Edit `backend/app/models/material.py` — add after `attributes`:

```python
    color_options: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    """Цвета, доступные для этого материала без изменения цены — извлечены
    из canonical_name при импорте, не пересчитываются на чтении. NULL или
    пустой список = материал не имеет цветового выбора. Список из ровно
    одного элемента отличается от NULL семантически, хотя для текущего
    каталога не встречается. См. ADR-0031."""
    color_fragment: Mapped[str | None] = mapped_column(String(50), nullable=True)
    """Точная подстрока в canonical_name, подлежащая замене при разрешении
    цвета (см. resolve_material_name) — например "(White/Bronze)" или
    "Bronze/White". Заполняется тем же проходом, что и color_options.
    См. ADR-0031 п.4."""
```

- [ ] **Step 2: Add column to `Project`**

Edit `backend/app/models/project.py` — add after `status`:

```python
    color_choice: Mapped[str | None] = mapped_column(String(20), nullable=True)
    """Единый цвет на весь проект для материалов с color_options. NULL =
    цвет ещё не выбран. Значение — один из известных цветов
    (app.services.material_naming.KNOWN_COLORS), не свободный текст.
    См. ADR-0031 п.2."""
```

- [ ] **Step 3: Generate the migration**

Run: `cd backend && alembic revision --autogenerate -m "add color_options/color_fragment to materials, color_choice to projects"`

Check the generated file's `down_revision` points at the current head
(`d4e7f2a9c6b1` per the latest file seen in this repo — verify with
`alembic heads` if autogenerate picks a different one). Confirm the
generated body only adds the three nullable columns, nothing else (no
unrelated autogenerate drift) — edit down to just:

```python
def upgrade() -> None:
    op.add_column("materials", sa.Column("color_options", sa.JSON(), nullable=True))
    op.add_column("materials", sa.Column("color_fragment", sa.String(length=50), nullable=True))
    op.add_column("projects", sa.Column("color_choice", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "color_choice")
    op.drop_column("materials", "color_fragment")
    op.drop_column("materials", "color_options")
```

- [ ] **Step 4: Apply the migration**

Run: `cd backend && alembic upgrade head`
Expected: succeeds, no errors.

- [ ] **Step 5: Verify with a quick round-trip**

Run: `cd backend && python -c "
from app.core.database import SessionLocal
from app.models import Material
db = SessionLocal()
m = db.query(Material).first()
print(m.color_options, m.color_fragment)
db.close()
"`
Expected: prints `None None` (columns exist, nullable, no data yet).

- [ ] **Step 6: Ruff check**

Run: `cd backend && ruff check app/models/material.py app/models/project.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/material.py backend/app/models/project.py backend/alembic/versions/
git commit -m "$(cat <<'EOF'
Add color_options/color_fragment/color_choice columns (ADR-0031)

Migration only, no backfill — see ADR-0031 "Последствия".

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Backfill script

**Files:**
- Create: `backend/app/scripts/backfill_color_options.py`
- Test: `backend/tests/scripts/test_backfill_color_options.py`

**Interfaces:**
- Consumes: `app.services.material_naming.parse_color` (Task 1),
  `Material.color_options`/`color_fragment` (Task 2).
- Produces: `def run_backfill(db: Session, apply: bool) -> BackfillReport`
  — used directly by tests and by `main()`'s CLI wrapper.
  `@dataclass class BackfillReport: recognized: list[BackfillRow]; unrecognized: list[str]`
  `@dataclass class BackfillRow: internal_sku: str; canonical_name: str; color_options: list[str]; color_fragment: str; pattern: str`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/scripts/test_backfill_color_options.py
"""Tests for the one-time color backfill script — see ADR-0031 п.1."""

from app.scripts.backfill_color_options import run_backfill


def test_backfill_dry_run_does_not_write_to_db(db_session, make_material):
    session, *_ = db_session
    material = make_material(sku="GUTR-DRY")
    material.canonical_name = 'Super Gutter End Cap 5" (White/Bronze)'
    session.commit()

    report = run_backfill(session, apply=False)

    assert len(report.recognized) == 1
    assert report.recognized[0].color_options == ["White", "Bronze"]
    session.expire_all()
    session.refresh(material)
    assert material.color_options is None
    assert material.color_fragment is None


def test_backfill_apply_writes_to_db(db_session, make_material):
    session, *_ = db_session
    material = make_material(sku="GUTR-APPLY")
    material.canonical_name = 'Super Gutter End Cap 5" (White/Bronze)'
    session.commit()

    run_backfill(session, apply=True)

    session.refresh(material)
    assert material.color_options == ["White", "Bronze"]
    assert material.color_fragment == "(White/Bronze)"


def test_backfill_bare_screws_format(db_session, make_material):
    session, *_ = db_session
    material = make_material(sku="SCRW-BARE")
    material.canonical_name = '12 x 3/4" Bronze/White Stainless steel'
    session.commit()

    report = run_backfill(session, apply=True)

    session.refresh(material)
    assert material.color_options == ["Bronze", "White"]
    assert material.color_fragment == "Bronze/White"
    assert report.recognized[0].pattern == "bare"


def test_backfill_single_color_parens_not_recognized(db_session, make_material):
    session, *_ = db_session
    material = make_material(sku="EFAS-1")
    material.canonical_name = "E-Fascia x 24' (White)"
    session.commit()

    report = run_backfill(session, apply=True)

    session.refresh(material)
    assert material.color_options is None
    assert material.color_fragment is None
    assert not any(r.internal_sku == "EFAS-1" for r in report.recognized)


def test_backfill_material_without_color_word_untouched(db_session, make_material):
    session, *_ = db_session
    material = make_material(sku="MISC-1")
    material.canonical_name = "Generic Bracket 4in"
    session.commit()

    report = run_backfill(session, apply=True)

    session.refresh(material)
    assert material.color_options is None
    assert not any(r.internal_sku == "MISC-1" for r in report.recognized)


def test_backfill_is_idempotent_on_second_run(db_session, make_material):
    session, *_ = db_session
    material = make_material(sku="GUTR-IDEMP")
    material.canonical_name = 'End Cap (White/Bronze)'
    session.commit()

    run_backfill(session, apply=True)
    session.refresh(material)
    first_options, first_fragment = material.color_options, material.color_fragment

    run_backfill(session, apply=True)
    session.refresh(material)

    assert material.color_options == first_options
    assert material.color_fragment == first_fragment


def test_backfill_skips_materials_already_backfilled(db_session, make_material):
    """A material with color_options already set (from a prior run or from
    import) is not reprocessed — mirrors the embedding backfill's
    embedding IS NULL guard."""
    session, *_ = db_session
    material = make_material(sku="GUTR-SKIP")
    material.canonical_name = 'End Cap (White/Bronze)'
    material.color_options = ["White", "Bronze"]
    material.color_fragment = "(White/Bronze)"
    session.commit()

    report = run_backfill(session, apply=True)

    assert not any(r.internal_sku == "GUTR-SKIP" for r in report.recognized)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/scripts/test_backfill_color_options.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the script**

```python
# backend/app/scripts/backfill_color_options.py
"""Одноразовый бэкафилл color_options/color_fragment для существующего
каталога Material — см. ADR-0031 п.1. Того же семейства, что
backfill_material_embeddings.py: dry-run по умолчанию, --apply для записи.

Идемпотентен: повторный запуск трогает только строки, у которых
color_options IS NULL (в т.ч. уже заполненные импортом новых материалов,
Task 5, не переобрабатываются).

Использование:
    python -m app.scripts.backfill_color_options            # dry-run
    python -m app.scripts.backfill_color_options --apply    # запись
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Material
from app.services.material_naming import parse_color


@dataclass
class BackfillRow:
    internal_sku: str
    canonical_name: str
    color_options: list[str]
    color_fragment: str
    pattern: str


@dataclass
class BackfillReport:
    recognized: list[BackfillRow] = field(default_factory=list)
    unrecognized: list[str] = field(default_factory=list)
    """canonical_name of materials that contain something color-shaped but
    were not recognized confidently — ADR-0031 п.1 step 2: must be listed
    explicitly, never silently skipped. Empty for the real catalog as of
    ADR-0031 Step 0, but the script must still report it if it ever
    happens."""


def run_backfill(db: Session, apply: bool) -> BackfillReport:
    materials = db.scalars(
        select(Material).where(Material.color_options.is_(None))
    ).all()

    report = BackfillReport()
    for material in materials:
        result = parse_color(material.canonical_name)
        if result is None:
            continue

        report.recognized.append(
            BackfillRow(
                internal_sku=material.internal_sku,
                canonical_name=material.canonical_name,
                color_options=result.color_options,
                color_fragment=result.color_fragment,
                pattern=result.pattern,
            )
        )
        if apply:
            material.color_options = result.color_options
            material.color_fragment = result.color_fragment

    if apply:
        db.commit()

    return report


def print_report(report: BackfillReport, apply: bool) -> None:
    print("=" * 70)
    print(f"Материалов распознано: {len(report.recognized)}")
    print("=" * 70)
    for row in report.recognized:
        print(
            f"  [{row.internal_sku}] {row.canonical_name!r}\n"
            f"      -> color_options={row.color_options} "
            f"color_fragment={row.color_fragment!r} (паттерн: {row.pattern})"
        )
    print()
    if report.unrecognized:
        print("=" * 70)
        print(f"НЕ смог распознать уверенно ({len(report.unrecognized)}):")
        print("=" * 70)
        for name in report.unrecognized:
            print(f"  - {name!r}")
        print()
    if apply:
        print(f"Записано в БД: {len(report.recognized)} материалов.")
    else:
        print(
            "Dry-run: ничего не изменено. Перезапусти с --apply, чтобы записать."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Реально записать color_options/color_fragment (без флага — dry-run).",
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

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/scripts/test_backfill_color_options.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Ruff check**

Run: `cd backend && ruff check app/scripts/backfill_color_options.py tests/scripts/test_backfill_color_options.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/app/scripts/backfill_color_options.py backend/tests/scripts/test_backfill_color_options.py
git commit -m "$(cat <<'EOF'
Add backfill_color_options.py, dry-run default (ADR-0031 п.1)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `create_orders_for_run` blocking guard

**Files:**
- Modify: `backend/app/allocation/order_service.py`
- Modify: `backend/app/api/order.py`
- Test: `backend/tests/allocation/test_order_color_choice.py`

**Interfaces:**
- Consumes: `Material.color_options` (Task 2), `Project.color_choice`
  (Task 2).
- Produces: `class ProjectColorChoiceRequiredError(Exception)` with
  attributes `project_id: uuid.UUID` and `material_names: list[str]` (the
  ambiguous materials found, for a useful error message) — caught in
  `app/api/order.py`'s `create_orders` handler, mapped to 409.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/allocation/test_order_color_choice.py
"""create_orders_for_run blocks when the plan includes a material with
color_options and Project.color_choice is NULL — see ADR-0031 п.3."""

import pytest

from app.allocation.order_service import (
    ProjectColorChoiceRequiredError,
    create_orders_for_run,
)
from app.allocation.service import run_allocation


def test_create_orders_blocked_when_color_choice_missing(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material(sku="GUTR-COLOR")
    material.canonical_name = 'End Cap (White/Bronze)'
    material.color_options = ["White", "Bronze"]
    material.color_fragment = "(White/Bronze)"
    session.commit()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    assert project.color_choice is None

    run = run_allocation(session, project.id)

    with pytest.raises(ProjectColorChoiceRequiredError):
        create_orders_for_run(session, project.id, run.id)


def test_create_orders_succeeds_when_color_choice_set(
    db_session, make_supplier, make_material, make_price, make_project
):
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material(sku="GUTR-COLOR2")
    material.canonical_name = 'End Cap (White/Bronze)'
    material.color_options = ["White", "Bronze"]
    material.color_fragment = "(White/Bronze)"
    session.commit()
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    project.color_choice = "White"
    session.commit()

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)

    assert len(orders) == 1


def test_create_orders_unaffected_for_projects_without_color_options(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Regression: projects whose materials never have color_options must
    keep working exactly as before — no new prompt, no new error."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material(sku="PLAIN-1")
    make_price(material, supplier, price=5.00, availability=10)
    project = make_project([(material, 10)])
    assert project.color_choice is None

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)

    assert len(orders) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/allocation/test_order_color_choice.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProjectColorChoiceRequiredError'`

- [ ] **Step 3: Add the exception and guard**

In `backend/app/allocation/order_service.py`, add near the other exception
classes (after `RunNotFoundError`):

```python
class ProjectColorChoiceRequiredError(Exception):
    """At least one material in this run's plan has non-empty color_options
    but Project.color_choice is NULL — the supplier-facing name would be
    ambiguous ("(White/Bronze)") if generation proceeded. See ADR-0031 п.3:
    this is a hard block, not a warning, because the missing information
    (which color) does not yet exist anywhere, not because the system
    disagrees with a decision the user already made."""

    def __init__(self, project_id: uuid.UUID, material_names: list[str]):
        self.project_id = project_id
        self.material_names = material_names
        super().__init__(
            f"Project {project_id} has materials with color options "
            f"({material_names}) but no color_choice set"
        )
```

Then in `create_orders_for_run`, insert the check right after the
`RunNotFoundError` guard (before the conflicts lookup), using the run's
lines rather than re-deriving the plan a second way:

```python
    run = db.get(AllocationRun, run_id)
    if run is None or run.project_id != project_id:
        raise RunNotFoundError(project_id, run_id)

    plan_material_ids = {
        line.material_id
        for line in db.scalars(
            select(AllocationLine).where(AllocationLine.allocation_run_id == run_id)
        ).all()
    }
    if plan_material_ids:
        materials_with_color_options = db.scalars(
            select(Material).where(
                Material.id.in_(plan_material_ids),
                Material.color_options.is_not(None),
            )
        ).all()
        if materials_with_color_options:
            project = db.get(Project, project_id)
            if project.color_choice is None:
                raise ProjectColorChoiceRequiredError(
                    project_id,
                    [m.canonical_name for m in materials_with_color_options],
                )
```

- [ ] **Step 4: Wire the 409 in the API layer**

In `backend/app/api/order.py`, import `ProjectColorChoiceRequiredError` and
add a handler in `create_orders`:

```python
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
    except ProjectColorChoiceRequiredError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Выберите цвет проекта, чтобы продолжить — в плане есть "
                "материалы с выбором цвета: " + ", ".join(exc.material_names)
            ),
        ) from exc
    except DraftOrderConflictError as exc:
        ...
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/allocation/test_order_color_choice.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full order test suite to check for regressions**

Run: `cd backend && pytest tests/allocation/ -v`
Expected: PASS, no regressions in existing `test_order.py`,
`test_order_draft_conflict.py`, etc.

- [ ] **Step 7: Ruff check**

Run: `cd backend && ruff check app/allocation/order_service.py app/api/order.py tests/allocation/test_order_color_choice.py`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add backend/app/allocation/order_service.py backend/app/api/order.py backend/tests/allocation/test_order_color_choice.py
git commit -m "$(cat <<'EOF'
Block Order creation when color_choice is missing (ADR-0031 п.3)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `PATCH /projects/{id}` — set/edit `color_choice`

**Files:**
- Modify: `backend/app/api/schemas/project.py`
- Modify: `backend/app/api/project.py`
- Test: `backend/tests/project/test_api.py` (extend)

**Interfaces:**
- Consumes: `Project.color_choice` (Task 2),
  `app.services.material_naming.KNOWN_COLORS` (Task 1).
- Produces: `ProjectUpdate.color_choice: str | None` (omittable field,
  independently optional from `title`), `ProjectOut.color_choice: str | None`.

- [ ] **Step 1: Write failing tests**

Check the existing test file first for its client/fixture pattern, then
append tests matching that pattern. Based on the read of
`backend/app/api/project.py`, the update endpoint takes a plain
`ProjectUpdate` body without checking `model_fields_set` today (it always
overwrites `title`). This task must not break that — `title` stays
required; `color_choice` becomes the first optional field on the schema.

```python
# append to backend/tests/project/test_api.py — adapt the client/fixture
# helper names to whatever this file already uses (check the top of the
# file for its own client-construction helper before writing this).

def test_patch_project_sets_color_choice(client, make_project_via_api):
    project = make_project_via_api(title="Color Test")

    response = client.patch(
        f"/projects/{project['id']}",
        json={"title": project["title"], "color_choice": "White"},
    )

    assert response.status_code == 200
    assert response.json()["color_choice"] == "White"


def test_patch_project_rejects_unknown_color(client, make_project_via_api):
    project = make_project_via_api(title="Color Test 2")

    response = client.patch(
        f"/projects/{project['id']}",
        json={"title": project["title"], "color_choice": "Green"},
    )

    assert response.status_code == 422


def test_patch_project_can_clear_color_choice(client, make_project_via_api):
    project = make_project_via_api(title="Color Test 3")
    client.patch(
        f"/projects/{project['id']}",
        json={"title": project["title"], "color_choice": "Bronze"},
    )

    response = client.patch(
        f"/projects/{project['id']}",
        json={"title": project["title"], "color_choice": None},
    )

    assert response.status_code == 200
    assert response.json()["color_choice"] is None


def test_patch_project_omitting_color_choice_leaves_it_untouched(client, make_project_via_api):
    project = make_project_via_api(title="Color Test 4")
    client.patch(
        f"/projects/{project['id']}",
        json={"title": project["title"], "color_choice": "White"},
    )

    response = client.patch(
        f"/projects/{project['id']}",
        json={"title": "Renamed, color untouched"},
    )

    assert response.status_code == 200
    assert response.json()["color_choice"] == "White"
```

Before finalizing this step, actually read
`backend/tests/project/test_api.py` and `backend/tests/project/conftest.py`
in full to match existing fixture names (`client`, project-creation helper)
exactly — do not guess names that don't exist in that file.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/project/test_api.py -v -k color_choice`
Expected: FAIL — 200/422 assertions fail because the field doesn't exist yet
(color_choice absent from response, or 422 not raised).

- [ ] **Step 3: Update the schema**

In `backend/app/api/schemas/project.py`:

```python
from app.services.material_naming import KNOWN_COLORS


class ProjectUpdate(BaseModel):
    title: str
    color_choice: str | None = Field(default=None)

    @field_validator("color_choice")
    @classmethod
    def _validate_color_choice(cls, value: str | None) -> str | None:
        if value is not None and value.upper() not in KNOWN_COLORS:
            raise ValueError(f"Unknown color: {value!r}")
        return value
```

Add `field_validator` to the existing `pydantic` import line. Also add
`color_choice: str | None` to `ProjectOut`:

```python
class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_by_user_id: uuid.UUID | None
    status: str
    created_at: datetime
    color_choice: str | None = None
```

- [ ] **Step 4: Update the endpoint to independently-optional-set `color_choice`**

In `backend/app/api/project.py`'s `update_project`, use
`model_fields_set` the same way `patch_order_item` does in `order.py`, so
omitting `color_choice` from the payload leaves it untouched while an
explicit `null` clears it:

```python
@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID, payload: ProjectUpdate, db: Session = Depends(get_db)
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project.title = payload.title
    if "color_choice" in payload.model_fields_set:
        project.color_choice = payload.color_choice
    db.commit()
    db.refresh(project)
    return project
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/project/test_api.py -v`
Expected: PASS, including pre-existing tests (no regression on plain
title-only PATCH).

- [ ] **Step 6: Ruff check**

Run: `cd backend && ruff check app/api/schemas/project.py app/api/project.py tests/project/test_api.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/schemas/project.py backend/app/api/project.py backend/tests/project/test_api.py
git commit -m "$(cat <<'EOF'
PATCH /projects/{id}: settable color_choice, validated against known colors

ADR-0031 п.2.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Extend xlsx import parsing for future materials

**Files:**
- Modify: `backend/app/scripts/xlsx_price_matrix.py`
- Modify: `backend/app/scripts/import_real_data.py`
- Test: create `backend/tests/scripts/test_xlsx_price_matrix.py` if none
  exists (check first with Glob — if one exists, extend it instead).

**Interfaces:**
- Consumes: `app.services.material_naming.parse_color` (Task 1).
- Produces: `MaterialRow.color_options: list[str] | None`,
  `MaterialRow.color_fragment: str | None` — consumed by
  `import_real_data.create_materials`.

- [ ] **Step 0: Check for an existing test file**

Run (Glob, not bash): search `backend/tests/scripts/test_xlsx_price_matrix.py`.
If found, read it fully before writing new tests so additions match its
existing fixture/style conventions (e.g. does it build an in-memory
openpyxl workbook, or call `parse_price_matrix` against a fixture file).

- [ ] **Step 1: Write failing test(s)**

If no fixture-building helper exists yet, test `MaterialRow` construction
directly against `parse_price_matrix`'s per-row logic by calling the
smallest unit that changes — since `parse_price_matrix` reads an actual
xlsx via openpyxl, prefer testing at the `MaterialRow` dataclass +
`parse_color` integration point instead of building a full workbook fixture
if that's expensive. Concretely:

```python
# backend/tests/scripts/test_xlsx_price_matrix.py
from app.scripts.xlsx_price_matrix import MaterialRow


def test_material_row_carries_color_fields_when_present():
    from app.services.material_naming import parse_color

    description = 'Super Gutter End Cap 5" (White/Bronze)'
    parsed = parse_color(description)
    row = MaterialRow(
        internal_sku="GUTR-001",
        description=description,
        category="Gutter",
        unit="pcs",
        used_fallback_unit=False,
        row_number=2,
        color_options=parsed.color_options if parsed else None,
        color_fragment=parsed.color_fragment if parsed else None,
    )
    assert row.color_options == ["White", "Bronze"]
    assert row.color_fragment == "(White/Bronze)"


def test_material_row_color_fields_none_when_no_color():
    row = MaterialRow(
        internal_sku="MISC-001",
        description="Generic Bracket 4in",
        category=None,
        unit="pcs",
        used_fallback_unit=False,
        row_number=5,
        color_options=None,
        color_fragment=None,
    )
    assert row.color_options is None
    assert row.color_fragment is None
```

(If an existing test file already exercises `parse_price_matrix` end-to-end
against a real/fixture xlsx, add one row-level assertion there instead that
checks `.color_options`/`.color_fragment` on a known two-color row, matching
that file's existing style — do not duplicate a whole new fixture workbook
if one already exists.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/scripts/test_xlsx_price_matrix.py -v`
Expected: FAIL — `TypeError: MaterialRow.__init__() got an unexpected keyword argument 'color_options'`

- [ ] **Step 3: Extend `MaterialRow` and populate it during parsing**

In `backend/app/scripts/xlsx_price_matrix.py`:

```python
from app.services.material_naming import parse_color

...

@dataclass
class MaterialRow:
    internal_sku: str
    description: str
    category: str | None
    unit: str
    used_fallback_unit: bool
    row_number: int  # 1-indexed sheet row, for diagnostics
    color_options: list[str] | None = None
    color_fragment: str | None = None
```

In `parse_price_matrix`, where `MaterialRow` is constructed:

```python
        color_result = parse_color(description)
        sku = _next_sku(current_category, sku_counters)
        result.materials.append(
            MaterialRow(
                internal_sku=sku,
                description=description,
                category=current_category,
                unit=unit,
                used_fallback_unit=used_fallback,
                row_number=row_number,
                color_options=color_result.color_options if color_result else None,
                color_fragment=color_result.color_fragment if color_result else None,
            )
        )
```

- [ ] **Step 4: Propagate into `import_real_data.create_materials`**

In `backend/app/scripts/import_real_data.py`, in `create_materials`:

```python
        material = Material(
            internal_sku=row.internal_sku,
            canonical_name=row.description,
            category=row.category,
            unit=row.unit,
            attributes={},
            color_options=row.color_options,
            color_fragment=row.color_fragment,
        )
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/scripts/test_xlsx_price_matrix.py -v`
Expected: PASS

- [ ] **Step 6: Run the full scripts test suite for regressions**

Run: `cd backend && pytest tests/scripts/ -v`
Expected: PASS, no regressions.

- [ ] **Step 7: Ruff check**

Run: `cd backend && ruff check app/scripts/xlsx_price_matrix.py app/scripts/import_real_data.py tests/scripts/`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add backend/app/scripts/xlsx_price_matrix.py backend/app/scripts/import_real_data.py backend/tests/scripts/test_xlsx_price_matrix.py
git commit -m "$(cat <<'EOF'
Extend xlsx import to populate color_options/color_fragment (ADR-0031)

Future imports get color parsing at import time, not only via the
one-time backfill script.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Full backend verification + real-catalog dry-run report

**Files:** none (verification only).

- [ ] **Step 1: Full test suite**

Run: `cd backend && pytest -q`
Expected: PASS, 0 failures.

- [ ] **Step 2: Full ruff check**

Run: `cd backend && ruff check .`
Expected: no errors.

- [ ] **Step 3: Run the backfill script in dry-run against the real catalog**

Run: `cd backend && python -m app.scripts.backfill_color_options`

Capture the **full** output (do not truncate) — this is what gets shown to
the user for manual review before they authorize `--apply`. Do not run
`--apply` in this task under any circumstance; that requires explicit
user sign-off after reviewing this output.

- [ ] **Step 4: Sanity-check the report programmatically**

Run: `cd backend && python -m app.scripts.backfill_color_options 2>&1 | grep -c "^  \["`

Compare against the ADR's stated expectation of ~149 recognized materials
(127 parenthetical + 22 bare). If the count differs meaningfully, stop and
investigate before presenting the report — a large discrepancy means the
regexes don't match Step 0's findings and something is wrong, not that the
catalog silently changed.

- [ ] **Step 5: Report to the user**

Paste the complete, untruncated dry-run output back to the user along with
the pytest/ruff results from Steps 1-2. Do not run `--apply`. Wait for
explicit confirmation.

---

## Self-Review Notes

- Spec coverage: all 6 numbered requirements from the task map to tasks
  1-6 (module+resolve = Task 1, migration = Task 2, backfill script =
  Task 3, blocking = Task 4, PATCH endpoint = Task 5, xlsx/import
  extension = Task 6). Task 7 covers the mandatory post-implementation
  dry-run report and the "don't run --apply yourself" constraint.
- All four `resolve_material_name` branches from ADR-0031 §4 have
  dedicated tests in Task 1.
- Both regex formats (parenthetical, bare) are tested with the literal
  Screws-category example from the ADR (`12 x 3/4" Bronze/White Stainless
  steel`) in Tasks 1, 3, and 6.
- Single-color-parens non-match is tested in Tasks 1 and 3.
- Idempotency of the backfill script is tested in Task 3.
- Regression (projects without color_options materials) is tested in
  Task 4.
- No frontend files are touched anywhere in this plan, per explicit scope.
