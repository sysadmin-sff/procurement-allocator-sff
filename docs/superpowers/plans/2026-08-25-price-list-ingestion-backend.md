# ADR-0019 Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the backend for AI price-list ingestion and matching
(ADR-0019): pgvector infrastructure, embedding-aware `Material` CRUD,
a one-time backfill script, a new `price_ingestion` module (extraction +
matching), and the price-list-import endpoints that write through to
`PriceListImport`/`PriceListEntry`/`SupplierMaterialAlias`/`Price`/`Material`.

**Architecture:** New `backend/app/price_ingestion/` module, structured like
`backend/app/order_response_parser/` (`client.py` for the OpenAI/pgvector
calls, `service.py` for orchestration and DB writes), but — unlike that
module — extraction and matching are two separate LLM steps because the
candidate space here is the whole `Material` table, not a closed 10–30-item
list (ADR-0019 §3). Matching is per-line: an exact-alias short-circuit first,
then pgvector top-5 + LLM decision. `Material.embedding` (pgvector,
nullable) is populated synchronously in `POST/PUT /materials` with graceful
degradation, and by a one-time idempotent backfill script for pre-existing
rows.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, `pgvector` (new Python
dependency + Postgres extension), OpenAI Python SDK (`embeddings.create`,
`responses.parse` for structured outputs — already a dependency), pytest,
ruff.

**Spec:** `docs/decisions/0019-price-list-ingestion-matching.md` (primary —
follow it exactly), cross-referencing `docs/decisions/0018-ai-order-response-parsing.md`
for the module-structure/graceful-degradation/config-driven-model precedent,
and `docs/spec.md` §3 for the original pipeline description.

## Global Constraints

- Do not change the schema of `PriceListImport`, `PriceListEntry`, or
  `SupplierMaterialAlias` — this ADR is the first code to read/write
  already-existing tables (ADR-0019 "Контекст"). Only `Material` gets a new
  column (`embedding`).
- Money/quantity logic stays backend-only (CLAUDE.md principle 4) — nothing
  here is frontend-facing yet.
- Material uniqueness is by `internal_sku`, never by raw string name
  (CLAUDE.md principle 3).
- LLM calls always end at a human-review gate; nothing here writes to
  `Price`/`Material` without an explicit `/apply` call on a reviewed entry
  (CLAUDE.md principle 2, ADR-0019 §2/§4/§5).
- `POST /materials` and `PUT /materials/{id}` must keep their existing
  status codes and required-field contracts — embedding is additive,
  invisible to callers except via graceful degradation (ADR-0019 §1).
- Model names are env-config (`OPENAI_EMBEDDING_MODEL`,
  `OPENAI_PRICE_INGESTION_MODEL`), never hardcoded — same pattern as
  `OPENAI_ORDER_RESPONSE_MODEL` (`backend/app/core/config.py:11`).
- Every new module/endpoint follows the existing repo conventions: Russian
  inline comments only where genuinely non-obvious (see existing files),
  English docstrings citing the ADR section they implement (as in
  `order_response_parser/client.py`), ruff clean (`ruff check .`), pytest
  green.

---

### Task 1: pgvector migration — `Material.embedding`

**Files:**
- Modify: `backend/pyproject.toml` (add `pgvector` dependency)
- Modify: `backend/app/models/material.py`
- Create: `backend/alembic/versions/<hash>_add_material_embedding.py`
- Test: `backend/tests/material/test_embedding_column.py`

**Interfaces:**
- Produces: `Material.embedding: Mapped[list[float] | None]` (pgvector
  `Vector(1536)`, nullable) — every later task that reads/writes embeddings
  imports `from app.models import Material` and uses `.embedding` as a
  plain Python `list[float] | None`.

- [ ] **Step 1: Add the `pgvector` dependency**

Edit `backend/pyproject.toml`, in the `dependencies` list (after
`"openai>=1.50",`):

```toml
    "openai>=1.50",
    "pgvector>=0.3.6",
    "python-multipart>=0.0.9",
```

Run: `pip install -e ./backend[dev]` (or `pip install pgvector>=0.3.6` if
the project uses an already-active editable install) so the package is
importable before writing code against it.

- [ ] **Step 2: Add `embedding` column to the `Material` model**

Edit `backend/app/models/material.py` — add the import and column:

```python
from pgvector.sqlalchemy import Vector
```

Add near the other `mapped_column` declarations:

```python
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    """text-embedding-3-small эмбеддинг canonical_name + attributes — см.
    ADR-0019 §1. NULL до бэкафилла/при сбое embeddings API (graceful
    degradation), исключается из векторного поиска матчинга."""
```

- [ ] **Step 3: Write the failing migration test**

Create `backend/tests/material/test_embedding_column.py`:

```python
"""pgvector extension + Material.embedding column — see ADR-0019 §1."""

from sqlalchemy import text

from app.core.database import engine


def test_vector_extension_is_installed():
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).first()
    assert result is not None


def test_material_embedding_column_exists_and_is_nullable(db_session, make_material):
    material = make_material()
    assert material.embedding is None


def test_material_embedding_column_stores_a_vector(db_session, make_material):
    session, _material_ids = db_session
    material = make_material()
    material.embedding = [0.1] * 1536
    session.commit()
    session.refresh(material)
    assert len(material.embedding) == 1536
    assert material.embedding[0] == pytest.approx(0.1)
```

Add `import pytest` at the top (needed for `pytest.approx`).

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && pytest tests/material/test_embedding_column.py -v`
Expected: FAIL — column `materials.embedding` does not exist / extension
not installed (no migration applied yet).

- [ ] **Step 5: Generate and write the migration**

Run: `cd backend && alembic revision -m "add material embedding column"`
to get a fresh revision id/filename, then edit the generated file (fill in
`down_revision` with the current head — check with
`alembic heads` if unsure) to:

```python
"""add material embedding column

Revision ID: <generated>
Revises: <current head>
Create Date: <generated>

"""
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "<generated>"
down_revision: str | None = "<current head>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "materials",
        sa.Column("embedding", Vector(1536), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("materials", "embedding")
    # Проверенное решение: не дропаем extension в downgrade — другие
    # объекты БД (индексы других веток миграций) могут на неё опираться;
    # DROP EXTENSION IF EXISTS vector CASCADE было бы разрушительнее, чем
    # нужно для отката одной колонки.
```

- [ ] **Step 6: Apply migration and run test to verify it passes**

Run: `cd backend && alembic upgrade head`
Run: `cd backend && pytest tests/material/test_embedding_column.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/app/models/material.py backend/alembic/versions/*_add_material_embedding.py backend/tests/material/test_embedding_column.py
git commit -m "feat: add pgvector Material.embedding column (ADR-0019)"
```

---

### Task 2: Embeddings client

**Files:**
- Create: `backend/app/price_ingestion/__init__.py`
- Create: `backend/app/price_ingestion/embeddings.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/price_ingestion/__init__.py`
- Test: `backend/tests/price_ingestion/test_embeddings.py`

**Interfaces:**
- Consumes: `app.core.config.settings.openai_api_key`,
  `settings.openai_embedding_model`.
- Produces: `embed_text(text: str) -> list[float]` (raises
  `EmbeddingError` on failure — imported by Task 3/5/6/7/8);
  `material_embedding_input(canonical_name: str, attributes: dict) -> str`
  (the exact serialization used everywhere a `Material`'s embedding input is
  built, so create/update/backfill/dup-check all agree).

- [ ] **Step 1: Add embedding config to Settings**

Edit `backend/app/core/config.py`:

```python
    openai_embedding_model: str = "text-embedding-3-small"
    """1536-dim, $0.02/1M tokens as of summer 2026 — see ADR-0019 §1.
    Config, not hardcoded, same pattern as openai_order_response_model."""
    openai_price_ingestion_model: str = "gpt-5.6-luna"
    """Provisional default = current ADR-0018 vision model, pending accuracy
    verification on real supplier price lists — see ADR-0019 §3."""
```

- [ ] **Step 2: Write the failing test for `material_embedding_input`**

Create `backend/tests/price_ingestion/__init__.py` (empty file).

Create `backend/tests/price_ingestion/test_embeddings.py`:

```python
"""Tests for app.price_ingestion.embeddings — see ADR-0019 §1.

embed_text always mocks the OpenAI client (no real API calls in this
suite) — this file only tests input serialization and error handling.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.price_ingestion.embeddings import (
    EmbeddingError,
    embed_text,
    material_embedding_input,
)


def test_material_embedding_input_combines_name_and_attributes():
    text = material_embedding_input(
        "84 in. 18x14 Fiberglass Screen", {"width_in": 84, "mesh": "18x14"}
    )
    assert "84 in. 18x14 Fiberglass Screen" in text
    assert "width_in" in text
    assert "84" in text


def test_material_embedding_input_handles_empty_attributes():
    text = material_embedding_input("Aluminum Frame Track", {})
    assert text.startswith("Aluminum Frame Track")


def _mock_openai_embeddings(vector):
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=vector)]
    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_response
    return patch("app.price_ingestion.embeddings.OpenAI", return_value=mock_client)


def test_embed_text_returns_vector_from_openai():
    fake_vector = [0.01] * 1536
    with _mock_openai_embeddings(fake_vector):
        with patch("app.price_ingestion.embeddings.settings") as mock_settings:
            mock_settings.openai_api_key = "fake-key"
            mock_settings.openai_embedding_model = "text-embedding-3-small"
            result = embed_text("some material text")
    assert result == fake_vector


def test_embed_text_raises_embedding_error_when_api_key_missing():
    with patch("app.price_ingestion.embeddings.settings") as mock_settings:
        mock_settings.openai_api_key = None
        with pytest.raises(EmbeddingError):
            embed_text("some material text")


def test_embed_text_raises_embedding_error_on_api_failure():
    from openai import APIError

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = APIError(
        "boom", request=MagicMock(), body=None
    )
    with patch("app.price_ingestion.embeddings.OpenAI", return_value=mock_client):
        with patch("app.price_ingestion.embeddings.settings") as mock_settings:
            mock_settings.openai_api_key = "fake-key"
            mock_settings.openai_embedding_model = "text-embedding-3-small"
            with pytest.raises(EmbeddingError):
                embed_text("some material text")
```

- [ ] **Step 2b: Run test to verify it fails**

Run: `cd backend && pytest tests/price_ingestion/test_embeddings.py -v`
Expected: FAIL — `app.price_ingestion.embeddings` does not exist.

- [ ] **Step 3: Implement the embeddings client**

Create `backend/app/price_ingestion/__init__.py` (empty file).

Create `backend/app/price_ingestion/embeddings.py`:

```python
"""Embeddings client for price-list matching — see ADR-0019 §1.

Used by Material create/update (graceful degradation on failure — the
caller decides what "failure" means for its own contract), the one-time
backfill script, and price_ingestion matching's candidate search and
duplicate-detection.
"""

from __future__ import annotations

import json

from openai import APIError, APITimeoutError, OpenAI

from app.core.config import settings


class EmbeddingError(Exception):
    """OpenAI embeddings API unreachable, timed out, errored, or no API key
    configured. Callers decide how to degrade — see ADR-0019 §1 (Material
    create/update swallow this; the backfill script and price_ingestion
    matching do not, since they have no "existing value" to fall back to)."""


def material_embedding_input(canonical_name: str, attributes: dict) -> str:
    """canonical_name + serialized attributes — see ADR-0019 §1, "Входной
    текст для эмбеддинга". Same function used everywhere an embedding input
    is built so create/update/backfill/matching never drift apart."""
    if not attributes:
        return canonical_name
    return f"{canonical_name} {json.dumps(attributes, sort_keys=True)}"


def embed_text(text: str) -> list[float]:
    """One OpenAI embeddings call. Raises EmbeddingError on any failure —
    never lets the raw OpenAI exception or a missing API key surface past
    this module."""
    if not settings.openai_api_key:
        raise EmbeddingError("OpenAI API не настроен (отсутствует OPENAI_API_KEY)")

    client = OpenAI(api_key=settings.openai_api_key)
    try:
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=text,
        )
    except (APIError, APITimeoutError) as exc:
        raise EmbeddingError(f"Embeddings API call failed: {exc}") from exc

    return list(response.data[0].embedding)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/price_ingestion/test_embeddings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/price_ingestion/__init__.py backend/app/price_ingestion/embeddings.py backend/app/core/config.py backend/tests/price_ingestion/
git commit -m "feat: add embeddings client for price-list matching (ADR-0019)"
```

---

### Task 3: `POST /materials` / `PUT /materials/{id}` — embedding with graceful degradation

**Files:**
- Modify: `backend/app/api/material.py`
- Test: `backend/tests/material/test_api.py` (add new tests, don't touch existing ones)

**Interfaces:**
- Consumes: `app.price_ingestion.embeddings.embed_text`,
  `material_embedding_input`, `EmbeddingError` (Task 2).
- Produces: no new interface — `create_material`/`update_material` behavior
  change only; response schema (`MaterialOut`) unchanged since `embedding`
  is not added to it (ADR-0019 never asks for embedding in API responses).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/material/test_api.py` (add `from unittest.mock
import patch` to the imports at the top):

```python
def test_create_material_embeds_synchronously(db_session):
    session, material_ids = db_session

    with patch(
        "app.api.material.embed_text", return_value=[0.2] * 1536
    ) as mock_embed:
        response = client.post(
            "/materials",
            json={
                "internal_sku": f"SKU-{uuid.uuid4().hex[:8]}",
                "canonical_name": "Embeddable Material",
                "unit": "ft",
            },
        )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))
    mock_embed.assert_called_once()

    material = session.get(__import__("app.models", fromlist=["Material"]).Material, uuid.UUID(body["id"]))
    assert material.embedding is not None
    assert len(material.embedding) == 1536


def test_create_material_survives_embedding_api_failure(db_session):
    from app.price_ingestion.embeddings import EmbeddingError

    session, material_ids = db_session

    with patch(
        "app.api.material.embed_text", side_effect=EmbeddingError("boom")
    ):
        response = client.post(
            "/materials",
            json={
                "internal_sku": f"SKU-{uuid.uuid4().hex[:8]}",
                "canonical_name": "Should Still Be Created",
                "unit": "ft",
            },
        )

    assert response.status_code == 201
    body = response.json()
    material_ids.append(uuid.UUID(body["id"]))

    from app.models import Material

    material = session.get(Material, uuid.UUID(body["id"]))
    assert material.embedding is None


def test_update_material_reembeds_when_canonical_name_changes(db_session, make_material):
    material = make_material(canonical_name="Old Name")

    with patch(
        "app.api.material.embed_text", return_value=[0.3] * 1536
    ) as mock_embed:
        response = client.put(
            f"/materials/{material.id}",
            json={"canonical_name": "New Name"},
        )

    assert response.status_code == 200
    mock_embed.assert_called_once()


def test_update_material_reembeds_when_attributes_change(db_session, make_material):
    material = make_material(canonical_name="Same Name", attributes={"gauge": "6"})

    with patch(
        "app.api.material.embed_text", return_value=[0.3] * 1536
    ) as mock_embed:
        response = client.put(
            f"/materials/{material.id}",
            json={"attributes": {"gauge": "8"}},
        )

    assert response.status_code == 200
    mock_embed.assert_called_once()


def test_update_material_does_not_reembed_when_only_category_changes(db_session, make_material):
    material = make_material(canonical_name="Stable Name")

    with patch("app.api.material.embed_text") as mock_embed:
        response = client.put(
            f"/materials/{material.id}",
            json={"category": "new-category"},
        )

    assert response.status_code == 200
    mock_embed.assert_not_called()


def test_update_material_keeps_old_embedding_on_reembed_failure(db_session, make_material):
    from app.price_ingestion.embeddings import EmbeddingError

    session, material_ids = db_session
    material = make_material(canonical_name="Old Name")
    material.embedding = [0.5] * 1536
    session.commit()

    with patch("app.api.material.embed_text", side_effect=EmbeddingError("boom")):
        response = client.put(
            f"/materials/{material.id}",
            json={"canonical_name": "New Name Triggers Reembed Attempt"},
        )

    assert response.status_code == 200
    session.refresh(material)
    assert material.embedding == [0.5] * 1536
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/material/test_api.py -v -k embed`
Expected: FAIL — `app.api.material.embed_text` does not exist yet
(create/update don't call it).

- [ ] **Step 3: Implement embedding in create_material/update_material**

Edit `backend/app/api/material.py`. Add imports:

```python
from app.price_ingestion.embeddings import EmbeddingError, embed_text, material_embedding_input
```

Replace `create_material`:

```python
@router.post("", response_model=MaterialOut, status_code=201)
def create_material(payload: MaterialCreate, db: Session = Depends(get_db)) -> Material:
    material = Material(
        internal_sku=payload.internal_sku,
        canonical_name=payload.canonical_name,
        category=payload.category,
        unit=payload.unit,
        attributes=payload.attributes,
    )
    try:
        material.embedding = embed_text(
            material_embedding_input(payload.canonical_name, payload.attributes)
        )
    except EmbeddingError:
        # Graceful degradation — see ADR-0019 §1: a manual CRUD create must
        # not become dependent on a third-party API's availability.
        # embedding stays NULL, picked up later by the backfill script.
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
```

Replace `update_material`:

```python
@router.put("/{material_id}", response_model=MaterialOut)
def update_material(
    material_id: uuid.UUID, payload: MaterialUpdate, db: Session = Depends(get_db)
) -> Material:
    """PATCH-семантика: поля, отсутствующие в payload, не трогаются."""
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
            # Graceful degradation — see ADR-0019 §1: keep the previous
            # embedding rather than clearing it; it's stale but still more
            # relevant than NULL for vector search.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/material/test_api.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/material.py backend/tests/material/test_api.py
git commit -m "feat: embed Material on create/update with graceful degradation (ADR-0019)"
```

---

### Task 4: Backfill script

**Files:**
- Create: `backend/app/scripts/backfill_material_embeddings.py`
- Test: `backend/tests/scripts/__init__.py`
- Test: `backend/tests/scripts/test_backfill_material_embeddings.py`

**Interfaces:**
- Consumes: `app.price_ingestion.embeddings.embed_text`,
  `material_embedding_input` (Task 2).
- Produces: `run_backfill(db: Session) -> int` (returns count of materials
  embedded — used by the test and by the `__main__` CLI entry point).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/scripts/__init__.py` (empty file).

Create `backend/tests/scripts/test_backfill_material_embeddings.py`:

```python
"""Tests for the one-time backfill script — see ADR-0019 §1.

Idempotent: only touches Material rows with embedding IS NULL.
"""

from unittest.mock import patch

from app.scripts.backfill_material_embeddings import run_backfill


def test_backfill_embeds_materials_with_null_embedding(db_session, make_material):
    session, _material_ids = db_session
    material = make_material(canonical_name="Needs Embedding")
    assert material.embedding is None

    with patch(
        "app.scripts.backfill_material_embeddings.embed_text",
        return_value=[0.4] * 1536,
    ):
        count = run_backfill(session)

    session.refresh(material)
    assert count >= 1
    assert material.embedding is not None
    assert len(material.embedding) == 1536


def test_backfill_does_not_touch_materials_with_existing_embedding(
    db_session, make_material
):
    session, _material_ids = db_session
    material = make_material(canonical_name="Already Embedded")
    material.embedding = [0.9] * 1536
    session.commit()

    with patch(
        "app.scripts.backfill_material_embeddings.embed_text"
    ) as mock_embed:
        run_backfill(session)

    mock_embed.assert_not_called()
    session.refresh(material)
    assert material.embedding == [0.9] * 1536


def test_backfill_is_idempotent_on_second_run(db_session, make_material):
    session, _material_ids = db_session
    make_material(canonical_name="Needs Embedding Twice")

    with patch(
        "app.scripts.backfill_material_embeddings.embed_text",
        return_value=[0.4] * 1536,
    ) as mock_embed:
        first_count = run_backfill(session)
        second_count = run_backfill(session)

    assert first_count >= 1
    assert second_count == 0
    assert mock_embed.call_count == first_count
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/scripts/test_backfill_material_embeddings.py -v`
Expected: FAIL — `app.scripts.backfill_material_embeddings` does not exist.

- [ ] **Step 3: Implement the backfill script**

Create `backend/app/scripts/backfill_material_embeddings.py`:

```python
"""Одноразовый бэкафилл эмбеддингов для Material с embedding IS NULL —
см. ADR-0019 §1. Того же семейства, что import_real_data.py/seed.py:
операторский скрипт, не API endpoint.

Идемпотентен: повторный запуск трогает только строки, у которых
embedding всё ещё NULL (например, из-за сбоя API при предыдущем запуске
или при create_material, ADR-0019 §1).

Использование:
    python -m app.scripts.backfill_material_embeddings
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Material
from app.price_ingestion.embeddings import EmbeddingError, embed_text, material_embedding_input


def run_backfill(db: Session) -> int:
    """Embeds every Material with embedding IS NULL. Returns the count of
    materials successfully embedded. A per-row EmbeddingError is logged and
    skipped (not raised) so one bad row doesn't abort the whole batch —
    left for the next run, same as any other embedding=NULL case."""
    materials = db.scalars(select(Material).where(Material.embedding.is_(None))).all()

    embedded_count = 0
    for material in materials:
        try:
            material.embedding = embed_text(
                material_embedding_input(material.canonical_name, material.attributes)
            )
        except EmbeddingError as exc:
            print(f"Skipping material {material.id} ({material.canonical_name!r}): {exc}")
            continue
        embedded_count += 1

    db.commit()
    return embedded_count


if __name__ == "__main__":
    session = SessionLocal()
    try:
        count = run_backfill(session)
        print(f"Embedded {count} material(s).")
    finally:
        session.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/scripts/test_backfill_material_embeddings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/backfill_material_embeddings.py backend/tests/scripts/
git commit -m "feat: add one-time Material embedding backfill script (ADR-0019)"
```

---

### Task 5: Extraction step (`price_ingestion/extraction.py`)

**Files:**
- Create: `backend/app/price_ingestion/extraction.py`
- Test: `backend/tests/price_ingestion/test_extraction.py`

**Interfaces:**
- Consumes: `app.core.config.settings.openai_api_key`,
  `settings.openai_price_ingestion_model`.
- Produces: `ExtractedPriceLine` (pydantic model: `raw_name: str,
  raw_sku: str | None, price: float, currency: str, availability: int |
  None, min_order_qty: int | None`), `extract_price_list_lines(*,
  file_bytes: bytes, content_type: str) -> list[ExtractedPriceLine]`,
  `PriceIngestionError`, `UnsupportedFileTypeError`,
  `validate_content_type(content_type: str | None) -> None` — all consumed
  by Task 8 (matching orchestration) and Task 9 (endpoint).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/price_ingestion/test_extraction.py`:

```python
"""Tests for app.price_ingestion.extraction (step 1, ADR-0019 §3) — pure
extraction, no matching. OpenAI call always mocked."""

from unittest.mock import MagicMock, patch

import pytest

from app.price_ingestion.extraction import (
    ExtractedPriceLine,
    PriceIngestionError,
    UnsupportedFileTypeError,
    extract_price_list_lines,
    validate_content_type,
)

FAKE_PDF_BYTES = b"%PDF-1.4 fake price list"


def test_validate_content_type_accepts_pdf():
    validate_content_type("application/pdf")


def test_validate_content_type_rejects_unsupported():
    with pytest.raises(UnsupportedFileTypeError):
        validate_content_type("text/plain")


def _mock_parse(lines):
    mock_response = MagicMock()
    mock_response.output_parsed = MagicMock(lines=lines)
    mock_client = MagicMock()
    mock_client.responses.parse.return_value = mock_response
    return patch("app.price_ingestion.extraction.OpenAI", return_value=mock_client)


def test_extract_returns_parsed_lines():
    lines = [
        ExtractedPriceLine(
            raw_name="Fiberglass Screen 18x14",
            raw_sku="FS-1814",
            price=5.10,
            currency="USD",
            availability=100,
            min_order_qty=1,
        )
    ]
    with _mock_parse(lines):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = "fake-key"
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            result = extract_price_list_lines(
                file_bytes=FAKE_PDF_BYTES, content_type="application/pdf"
            )
    assert result == lines


def test_extract_raises_price_ingestion_error_when_api_key_missing():
    with patch("app.price_ingestion.extraction.settings") as mock_settings:
        mock_settings.openai_api_key = None
        with pytest.raises(PriceIngestionError):
            extract_price_list_lines(
                file_bytes=FAKE_PDF_BYTES, content_type="application/pdf"
            )


def test_extract_raises_price_ingestion_error_on_api_failure():
    from openai import APIError

    mock_client = MagicMock()
    mock_client.responses.parse.side_effect = APIError(
        "boom", request=MagicMock(), body=None
    )
    with patch("app.price_ingestion.extraction.OpenAI", return_value=mock_client):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = "fake-key"
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            with pytest.raises(PriceIngestionError):
                extract_price_list_lines(
                    file_bytes=FAKE_PDF_BYTES, content_type="application/pdf"
                )


def test_extract_returns_empty_list_when_model_finds_nothing():
    with _mock_parse([]):
        with patch("app.price_ingestion.extraction.settings") as mock_settings:
            mock_settings.openai_api_key = "fake-key"
            mock_settings.openai_price_ingestion_model = "gpt-5.6-luna"
            result = extract_price_list_lines(
                file_bytes=FAKE_PDF_BYTES, content_type="application/pdf"
            )
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/price_ingestion/test_extraction.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement extraction**

Create `backend/app/price_ingestion/extraction.py`:

```python
"""Step 1 of price-list ingestion: extraction only, no matching — see
ADR-0019 §3. Structurally separate from matching (extraction.py vs
matching.py) because the candidate space for matching is the whole
Material table, unlike ADR-0018's single-call approach where the closed
OrderItem list fits in the same prompt as the document.
"""

from __future__ import annotations

import base64

from openai import APIError, APITimeoutError, OpenAI
from pydantic import BaseModel

from app.core.config import settings


class ExtractedPriceLine(BaseModel):
    raw_name: str
    raw_sku: str | None
    price: float
    currency: str
    availability: int | None
    min_order_qty: int | None


class _ExtractionResult(BaseModel):
    lines: list[ExtractedPriceLine]


class PriceIngestionError(Exception):
    """OpenAI API unreachable, timed out, or returned an error — mirrors
    OrderResponseParsingError (ADR-0018 §6)."""


_SUPPORTED_CONTENT_TYPES = {
    "application/pdf": "input_file",
    "image/png": "input_image",
    "image/jpeg": "input_image",
    "image/webp": "input_image",
}


class UnsupportedFileTypeError(Exception):
    def __init__(self, content_type: str | None):
        self.content_type = content_type
        super().__init__(f"Unsupported file content type: {content_type}")


def validate_content_type(content_type: str | None) -> None:
    if content_type not in _SUPPORTED_CONTENT_TYPES:
        raise UnsupportedFileTypeError(content_type)


_PROMPT = """\
Ты помогаешь сотруднику отдела закупок извлечь строки из прайс-листа \
поставщика. Прикреплённый документ — прайс-лист (PDF или скан/фото).

Извлеки КАЖДУЮ строку прайса как отдельную позицию. Не пытайся сопоставить \
её ни с чем — только извлечение. Для каждой строки верни:
- raw_name: название материала дословно, как написано в прайсе
- raw_sku: артикул поставщика, если указан; null, если нет
- price: цена за единицу
- currency: валюта (обычно "USD")
- availability: остаток на складе, если указан; null, если нет
- min_order_qty: минимальное количество заказа, если указано; null, если нет

Если документ нечитаем или не содержит ни одной позиции с ценой — верни \
пустой список lines, не пытайся выдумать позиции.
"""


def extract_price_list_lines(
    *, file_bytes: bytes, content_type: str
) -> list[ExtractedPriceLine]:
    """One OpenAI call: vision + structured output, extraction only (no
    matching — see module docstring / ADR-0019 §3). Raises
    PriceIngestionError on any API failure. An empty extraction (model
    found nothing) is not an error and returns an empty list normally."""
    if not settings.openai_api_key:
        raise PriceIngestionError(
            "OpenAI API не настроен (отсутствует OPENAI_API_KEY)"
        )

    client = OpenAI(api_key=settings.openai_api_key)

    file_field = _SUPPORTED_CONTENT_TYPES[content_type]
    encoded = base64.b64encode(file_bytes).decode("ascii")
    data_url = f"data:{content_type};base64,{encoded}"

    if file_field == "input_file":
        file_content = {
            "type": "input_file",
            "filename": "price-list.pdf",
            "file_data": data_url,
        }
    else:
        file_content = {"type": "input_image", "image_url": data_url}

    try:
        response = client.responses.parse(
            model=settings.openai_price_ingestion_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": _PROMPT},
                        file_content,
                    ],
                }
            ],
            text_format=_ExtractionResult,
        )
    except (APIError, APITimeoutError) as exc:
        raise PriceIngestionError(
            "Не удалось связаться с сервисом распознавания. Попробуйте ещё раз."
        ) from exc

    parsed = response.output_parsed
    if parsed is None:
        raise PriceIngestionError("Не удалось распознать документ.")

    return parsed.lines
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/price_ingestion/test_extraction.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/price_ingestion/extraction.py backend/tests/price_ingestion/test_extraction.py
git commit -m "feat: add price-list extraction step (ADR-0019 §3)"
```

---

### Task 6: Vector candidate search + alias short-circuit

**Files:**
- Create: `backend/app/price_ingestion/candidates.py`
- Test: `backend/tests/price_ingestion/test_candidates.py`

**Interfaces:**
- Consumes: `Material` (with `.embedding`), `SupplierMaterialAlias`.
- Produces: `TOP_K = 5`, `DUPLICATE_DISTANCE_THRESHOLD: float` (module
  constant, reused by Task 8's duplicate-detection so there is only one
  threshold, per ADR-0019 §4); `find_known_alias(db: Session, supplier_id:
  uuid.UUID, raw_name: str) -> SupplierMaterialAlias | None`;
  `find_top_candidates(db: Session, embedding: list[float], k: int =
  TOP_K) -> list[Material]` (excludes `embedding IS NULL`, ordered by
  cosine distance ascending).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/price_ingestion/test_candidates.py`:

```python
"""Tests for app.price_ingestion.candidates — see ADR-0019 §2/§3.

Requires a real Postgres with pgvector (same DB as the rest of the test
suite) since these tests exercise the actual <=> operator and DB
constraints, not mocks.
"""

import uuid

from app.models import SupplierMaterialAlias
from app.price_ingestion.candidates import find_known_alias, find_top_candidates


def test_find_known_alias_returns_exact_match(db_session, make_supplier, make_material):
    session, _material_ids, supplier_ids = db_session
    supplier = make_supplier()
    material = make_material()
    alias = SupplierMaterialAlias(
        supplier_id=supplier.id,
        material_id=material.id,
        supplier_raw_name="ACME Fiberglass 18x14",
    )
    session.add(alias)
    session.commit()

    found = find_known_alias(session, supplier.id, "ACME Fiberglass 18x14")

    assert found is not None
    assert found.material_id == material.id


def test_find_known_alias_returns_none_when_no_match(db_session, make_supplier):
    session, _material_ids, supplier_ids = db_session
    supplier = make_supplier()

    found = find_known_alias(session, supplier.id, "Never Seen Before")

    assert found is None


def test_find_known_alias_is_scoped_to_supplier(db_session, make_supplier, make_material):
    session, _material_ids, supplier_ids = db_session
    supplier_a = make_supplier(name="Supplier A")
    supplier_b = make_supplier(name="Supplier B")
    material = make_material()
    session.add(
        SupplierMaterialAlias(
            supplier_id=supplier_a.id,
            material_id=material.id,
            supplier_raw_name="Shared Raw Name",
        )
    )
    session.commit()

    found = find_known_alias(session, supplier_b.id, "Shared Raw Name")

    assert found is None


def test_find_top_candidates_orders_by_cosine_distance(db_session, make_material):
    session, _material_ids, _supplier_ids = db_session
    close = make_material(canonical_name="Close Match")
    close.embedding = [1.0] + [0.0] * 1535
    far = make_material(canonical_name="Far Match")
    far.embedding = [0.0, 1.0] + [0.0] * 1534
    session.commit()

    query_vector = [0.99] + [0.01] * 1535
    results = find_top_candidates(session, query_vector, k=5)

    result_ids = [m.id for m in results]
    assert close.id in result_ids
    assert result_ids.index(close.id) < result_ids.index(far.id)


def test_find_top_candidates_excludes_null_embedding(db_session, make_material):
    session, _material_ids, _supplier_ids = db_session
    no_embedding = make_material(canonical_name="No Embedding")
    assert no_embedding.embedding is None

    query_vector = [0.5] * 1536
    results = find_top_candidates(session, query_vector, k=5)

    assert no_embedding.id not in [m.id for m in results]


def test_find_top_candidates_respects_k_limit(db_session, make_material):
    session, _material_ids, _supplier_ids = db_session
    for i in range(7):
        m = make_material(canonical_name=f"Material {i}")
        m.embedding = [float(i)] + [0.0] * 1535
    session.commit()

    results = find_top_candidates(session, [0.0] * 1536, k=5)

    assert len(results) == 5
```

Note: reuses the `db_session`/`make_supplier`/`make_material` fixtures —
add a `conftest.py` in `backend/tests/price_ingestion/` re-exporting them
from the existing `tests/price/conftest.py` pattern (same fixture shape:
`db_session` yields `(session, material_ids, supplier_ids)`).

- [ ] **Step 1b: Add conftest for price_ingestion tests**

Create `backend/tests/price_ingestion/conftest.py`:

```python
import uuid

import pytest

from app.core.database import SessionLocal, get_db
from app.main import app
from app.models import (
    Material,
    Price,
    PriceListEntry,
    PriceListImport,
    Supplier,
    SupplierMaterialAlias,
)


@pytest.fixture
def db_session():
    session = SessionLocal()
    material_ids: list = []
    supplier_ids: list = []

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session, material_ids, supplier_ids
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.rollback()
        if supplier_ids:
            session.query(SupplierMaterialAlias).filter(
                SupplierMaterialAlias.supplier_id.in_(supplier_ids)
            ).delete(synchronize_session=False)
            import_ids = [
                i.id
                for i in session.query(PriceListImport)
                .filter(PriceListImport.supplier_id.in_(supplier_ids))
                .all()
            ]
            if import_ids:
                session.query(PriceListEntry).filter(
                    PriceListEntry.import_id.in_(import_ids)
                ).delete(synchronize_session=False)
                session.query(PriceListImport).filter(
                    PriceListImport.id.in_(import_ids)
                ).delete(synchronize_session=False)
        if material_ids:
            session.query(SupplierMaterialAlias).filter(
                SupplierMaterialAlias.material_id.in_(material_ids)
            ).delete(synchronize_session=False)
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
        session.commit()
        session.close()


@pytest.fixture
def make_supplier(db_session):
    session, _material_ids, supplier_ids = db_session

    def _make(name="Test Supplier"):
        supplier = Supplier(name=name, currency="USD", delivery_policy={})
        session.add(supplier)
        session.flush()
        supplier_ids.append(supplier.id)
        return supplier

    return _make


@pytest.fixture
def make_material(db_session):
    session, material_ids, _supplier_ids = db_session

    def _make(canonical_name=None, unit="ft", attributes=None):
        sku = f"TEST-SKU-{uuid.uuid4().hex[:12]}"
        material = Material(
            internal_sku=sku,
            canonical_name=canonical_name or sku,
            unit=unit,
            attributes=attributes or {},
        )
        session.add(material)
        session.flush()
        material_ids.append(material.id)
        return material

    return _make
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/price_ingestion/test_candidates.py -v`
Expected: FAIL — `app.price_ingestion.candidates` does not exist.

- [ ] **Step 3: Implement candidate search**

Create `backend/app/price_ingestion/candidates.py`:

```python
"""Alias short-circuit and pgvector top-K candidate search — see ADR-0019
§2/§3. TOP_K and DUPLICATE_DISTANCE_THRESHOLD are shared constants: the
same distance cutoff used to decide "is this Material a match candidate"
is reused in matching.py to decide "are two new lines probably the same
material" (ADR-0019 §4 — deliberately one threshold, not two).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Material, SupplierMaterialAlias

TOP_K = 5
DUPLICATE_DISTANCE_THRESHOLD = 0.15
"""Cosine distance below which two embeddings are considered the same
underlying material — used both to cut off top-K candidates worth showing
the LLM and to flag possible duplicate new-lines (ADR-0019 §4). Not
validated against real data yet — see docs/known-issues.md."""


def find_known_alias(
    db: Session, supplier_id: uuid.UUID, raw_name: str
) -> SupplierMaterialAlias | None:
    """Exact-match short-circuit before any embedding/LLM call — see
    ADR-0019 §2. Scoped to (supplier_id, supplier_raw_name)."""
    return db.scalar(
        select(SupplierMaterialAlias).where(
            SupplierMaterialAlias.supplier_id == supplier_id,
            SupplierMaterialAlias.supplier_raw_name == raw_name,
        )
    )


def find_top_candidates(
    db: Session, embedding: list[float], k: int = TOP_K
) -> list[Material]:
    """Top-k Material by cosine distance to `embedding`, excluding rows
    with embedding IS NULL (they simply can't be searched — ADR-0019 §1,
    "деградация полноты поиска, не ошибка")."""
    return list(
        db.scalars(
            select(Material)
            .where(Material.embedding.is_not(None))
            .order_by(Material.embedding.cosine_distance(embedding))
            .limit(k)
        ).all()
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/price_ingestion/test_candidates.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/price_ingestion/candidates.py backend/tests/price_ingestion/test_candidates.py backend/tests/price_ingestion/conftest.py
git commit -m "feat: add alias short-circuit and pgvector candidate search (ADR-0019 §2-3)"
```

---

### Task 7: LLM matching decision

**Files:**
- Create: `backend/app/price_ingestion/matching.py`
- Test: `backend/tests/price_ingestion/test_matching.py`

**Interfaces:**
- Consumes: `ExtractedPriceLine` (Task 5), `find_known_alias`,
  `find_top_candidates`, `TOP_K`, `DUPLICATE_DISTANCE_THRESHOLD` (Task 6),
  `embed_text`, `material_embedding_input` (Task 2).
- Produces: `MatchDecision` (pydantic: `action: Literal["match", "new"]`,
  `material_id: uuid.UUID | None`, `confidence: float`, `reasoning: str`,
  `suggested_internal_sku: str | None`); `MatchedLine` (dataclass:
  `extracted: ExtractedPriceLine`, `decision: MatchDecision`,
  `embedding: list[float]`, `possible_duplicate_of: list[int]` — index
  positions within the batch); `match_price_list_lines(db: Session,
  supplier_id: uuid.UUID, lines: list[ExtractedPriceLine]) ->
  list[MatchedLine]` — consumed by Task 9 (endpoint orchestration).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/price_ingestion/test_matching.py`:

```python
"""Tests for app.price_ingestion.matching — see ADR-0019 §2-4.

Alias short-circuit must skip embedding + LLM calls entirely (asserted via
mock.assert_not_called on both). Normal path mocks both embed_text and the
LLM decision call. Duplicate-detection reuses embeddings already computed
during matching, so no extra embed_text call is needed for that step.
"""

import uuid
from unittest.mock import patch

from app.models import SupplierMaterialAlias
from app.price_ingestion.extraction import ExtractedPriceLine
from app.price_ingestion.matching import MatchDecision, match_price_list_lines


def _line(raw_name="Some Material", price=10.0, raw_sku=None):
    return ExtractedPriceLine(
        raw_name=raw_name,
        raw_sku=raw_sku,
        price=price,
        currency="USD",
        availability=None,
        min_order_qty=None,
    )


def test_known_alias_skips_embedding_and_llm_entirely(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    material = make_material()
    session.add(
        SupplierMaterialAlias(
            supplier_id=supplier.id,
            material_id=material.id,
            supplier_raw_name="Known Raw Name",
        )
    )
    session.commit()

    line = _line(raw_name="Known Raw Name")

    with patch("app.price_ingestion.matching.embed_text") as mock_embed, patch(
        "app.price_ingestion.matching._decide_match"
    ) as mock_llm:
        results = match_price_list_lines(session, supplier.id, [line])

    mock_embed.assert_not_called()
    mock_llm.assert_not_called()
    assert len(results) == 1
    assert results[0].decision.action == "match"
    assert results[0].decision.material_id == material.id
    assert results[0].decision.confidence == 1.0
    assert results[0].decision.reasoning == "known alias"


def test_unknown_line_goes_through_vector_search_and_llm(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    candidate = make_material(canonical_name="Candidate Material")
    candidate.embedding = [0.5] * 1536
    session.commit()

    line = _line(raw_name="New Raw Name")
    fake_decision = MatchDecision(
        action="match",
        material_id=candidate.id,
        confidence=0.9,
        reasoning="matches by attributes",
        suggested_internal_sku=None,
    )

    with patch(
        "app.price_ingestion.matching.embed_text", return_value=[0.5] * 1536
    ) as mock_embed, patch(
        "app.price_ingestion.matching._decide_match", return_value=fake_decision
    ) as mock_llm:
        results = match_price_list_lines(session, supplier.id, [line])

    mock_embed.assert_called_once()
    mock_llm.assert_called_once()
    assert results[0].decision.action == "match"
    assert results[0].decision.material_id == candidate.id


def test_two_new_lines_with_close_embeddings_flag_each_other_as_duplicates(
    db_session, make_supplier
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    line_a = _line(raw_name="Screen Type A")
    line_b = _line(raw_name="Screen Type A Variant")

    decision_new = MatchDecision(
        action="new",
        material_id=None,
        confidence=0.8,
        reasoning="no close match found",
        suggested_internal_sku="NEW-SKU-1",
    )

    close_embedding_a = [1.0] + [0.0] * 1535
    close_embedding_b = [0.99] + [0.01] * 1535

    with patch(
        "app.price_ingestion.matching.embed_text",
        side_effect=[close_embedding_a, close_embedding_b],
    ), patch(
        "app.price_ingestion.matching._decide_match", return_value=decision_new
    ):
        results = match_price_list_lines(session, supplier.id, [line_a, line_b])

    assert results[0].possible_duplicate_of == [1]
    assert results[1].possible_duplicate_of == [0]


def test_new_lines_with_far_embeddings_do_not_flag_each_other(
    db_session, make_supplier
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    line_a = _line(raw_name="Screen Type A")
    line_b = _line(raw_name="Completely Different Item")

    decision_new = MatchDecision(
        action="new",
        material_id=None,
        confidence=0.8,
        reasoning="no close match found",
        suggested_internal_sku="NEW-SKU-1",
    )

    far_embedding_a = [1.0] + [0.0] * 1535
    far_embedding_b = [0.0, 1.0] + [0.0] * 1534

    with patch(
        "app.price_ingestion.matching.embed_text",
        side_effect=[far_embedding_a, far_embedding_b],
    ), patch(
        "app.price_ingestion.matching._decide_match", return_value=decision_new
    ):
        results = match_price_list_lines(session, supplier.id, [line_a, line_b])

    assert results[0].possible_duplicate_of == []
    assert results[1].possible_duplicate_of == []


def test_matched_lines_are_not_considered_for_duplicate_detection(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    candidate = make_material()
    candidate.embedding = [1.0] + [0.0] * 1535
    session.commit()

    line_a = _line(raw_name="Matched Line")
    line_b = _line(raw_name="New Line")

    decision_match = MatchDecision(
        action="match",
        material_id=candidate.id,
        confidence=0.9,
        reasoning="matches",
        suggested_internal_sku=None,
    )
    decision_new = MatchDecision(
        action="new",
        material_id=None,
        confidence=0.8,
        reasoning="no match",
        suggested_internal_sku="NEW-SKU-2",
    )

    with patch(
        "app.price_ingestion.matching.embed_text",
        side_effect=[[1.0] + [0.0] * 1535, [1.0] + [0.0] * 1535],
    ), patch(
        "app.price_ingestion.matching._decide_match",
        side_effect=[decision_match, decision_new],
    ):
        results = match_price_list_lines(session, supplier.id, [line_a, line_b])

    assert results[0].possible_duplicate_of == []
    assert results[1].possible_duplicate_of == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/price_ingestion/test_matching.py -v`
Expected: FAIL — `app.price_ingestion.matching` does not exist.

- [ ] **Step 3: Implement matching**

Create `backend/app/price_ingestion/matching.py`:

```python
"""Step 2 of price-list ingestion: matching, one call per line — see
ADR-0019 §2-4. Exact-alias short-circuit skips embedding + LLM entirely;
otherwise pgvector top-K + LLM decision. After all lines are matched,
new-line embeddings (already computed for candidate search — reused, not
recomputed) are pairwise-compared to flag possible duplicates within the
same import (ADR-0019 §4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from openai import APIError, APITimeoutError, OpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Material
from app.price_ingestion.candidates import (
    DUPLICATE_DISTANCE_THRESHOLD,
    find_known_alias,
    find_top_candidates,
)
from app.price_ingestion.embeddings import embed_text, material_embedding_input
from app.price_ingestion.extraction import ExtractedPriceLine, PriceIngestionError


class MatchDecision(BaseModel):
    action: Literal["match", "new"]
    material_id: uuid.UUID | None
    confidence: float
    reasoning: str
    suggested_internal_sku: str | None


@dataclass
class MatchedLine:
    extracted: ExtractedPriceLine
    decision: MatchDecision
    embedding: list[float]
    possible_duplicate_of: list[int] = field(default_factory=list)


def _candidate_context(candidates: list[Material]) -> str:
    lines = [
        f"- id={m.id}, название={m.canonical_name!r}, категория={m.category!r}, "
        f"единица={m.unit!r}, атрибуты={m.attributes!r}"
        for m in candidates
    ]
    return "\n".join(lines) if lines else "(нет кандидатов)"


_PROMPT_TEMPLATE = """\
Ты помогаешь сотруднику отдела закупок сопоставить строку прайс-листа \
поставщика с уже известной базой материалов.

Строка прайса: название={raw_name!r}, артикул поставщика={raw_sku!r}.

Похожие материалы из нашей базы (топ-5 по векторному сходству):
{candidates_context}

Реши: это уже известный нам материал (один из списка выше) или новый, \
которого ещё нет в базе?

Верни:
- action: "match", если это один из материалов выше; "new", если это \
новый материал, которого нет в списке
- material_id: id материала из списка выше, если action="match"; null, \
если action="new"
- confidence: число от 0 до 1 — насколько ты уверен в решении
- reasoning: кратко, почему принято такое решение
- suggested_internal_sku: если action="new", предложи черновой internal_sku \
(короткий, по образцу существующих в базе, например на основе категории/ \
названия); null, если action="match"
"""


def _decide_match(
    raw_name: str, raw_sku: str | None, candidates: list[Material]
) -> MatchDecision:
    if not settings.openai_api_key:
        raise PriceIngestionError(
            "OpenAI API не настроен (отсутствует OPENAI_API_KEY)"
        )

    client = OpenAI(api_key=settings.openai_api_key)
    prompt = _PROMPT_TEMPLATE.format(
        raw_name=raw_name,
        raw_sku=raw_sku,
        candidates_context=_candidate_context(candidates),
    )

    try:
        response = client.responses.parse(
            model=settings.openai_price_ingestion_model,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            text_format=MatchDecision,
        )
    except (APIError, APITimeoutError) as exc:
        raise PriceIngestionError(
            "Не удалось связаться с сервисом сопоставления. Попробуйте ещё раз."
        ) from exc

    parsed = response.output_parsed
    if parsed is None:
        raise PriceIngestionError("Не удалось сопоставить строку прайса.")
    return parsed


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)


def _flag_duplicate_new_lines(results: list[MatchedLine]) -> None:
    """Pairwise cosine distance between all action="new" lines in this
    batch, reusing embeddings already computed during matching — see
    ADR-0019 §4. Mutates possible_duplicate_of on the affected results."""
    new_indices = [i for i, r in enumerate(results) if r.decision.action == "new"]
    for i in new_indices:
        for j in new_indices:
            if i == j:
                continue
            distance = _cosine_distance(results[i].embedding, results[j].embedding)
            if distance < DUPLICATE_DISTANCE_THRESHOLD:
                results[i].possible_duplicate_of.append(j)


def match_price_list_lines(
    db: Session, supplier_id: uuid.UUID, lines: list[ExtractedPriceLine]
) -> list[MatchedLine]:
    """Matches each extracted line — alias short-circuit first (ADR-0019
    §2), otherwise vector search + LLM (ADR-0019 §3) — then flags
    possible duplicate action="new" lines within this batch (ADR-0019 §4).
    """
    results: list[MatchedLine] = []

    for line in lines:
        known_alias = find_known_alias(db, supplier_id, line.raw_name)
        if known_alias is not None:
            decision = MatchDecision(
                action="match",
                material_id=known_alias.material_id,
                confidence=1.0,
                reasoning="known alias",
                suggested_internal_sku=None,
            )
            # Эмбеддинг не нужен для known-alias пути (ADR-0019 §2), но
            # possible_duplicate_of применяется только к action="new" —
            # пустой вектор здесь никогда не используется в сравнении.
            results.append(MatchedLine(extracted=line, decision=decision, embedding=[]))
            continue

        embedding = embed_text(material_embedding_input(line.raw_name, {}))
        candidates = find_top_candidates(db, embedding)
        decision = _decide_match(line.raw_name, line.raw_sku, candidates)
        results.append(MatchedLine(extracted=line, decision=decision, embedding=embedding))

    _flag_duplicate_new_lines(results)
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/price_ingestion/test_matching.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/price_ingestion/matching.py backend/tests/price_ingestion/test_matching.py
git commit -m "feat: add price-list matching with alias short-circuit and duplicate detection (ADR-0019 §2-4)"
```

---

### Task 8: Apply-entry service — writes to Material/Price/SupplierMaterialAlias

**Files:**
- Create: `backend/app/price_ingestion/apply.py`
- Test: `backend/tests/price_ingestion/test_apply.py`

**Interfaces:**
- Consumes: `PriceListEntry`, `PriceListImport`, `Material`, `Price`,
  `SupplierMaterialAlias` models; `embed_text`, `material_embedding_input`
  (Task 2).
- Produces: `EntryNotFoundError`, `apply_price_list_entry(db: Session,
  import_id: uuid.UUID, entry_id: uuid.UUID, *, action: Literal["match",
  "new", "skip"], material_id: uuid.UUID | None = None, internal_sku: str
  | None = None, canonical_name: str | None = None) -> PriceListEntry` —
  consumed by Task 9 (endpoint).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/price_ingestion/test_apply.py`:

```python
"""Tests for app.price_ingestion.apply — see ADR-0019 §5.

Covers: match applies a version-bumped Price + upserts alias; new creates
Material+Alias+Price atomically, rolling back all three on partial
failure; match on an existing active Price closes the old one.
"""

import datetime
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Material, Price, PriceListEntry, PriceListImport, SupplierMaterialAlias
from app.price_ingestion.apply import EntryNotFoundError, apply_price_list_entry


def _make_import(session, supplier):
    price_list_import = PriceListImport(
        supplier_id=supplier.id,
        file_ref="test.pdf",
        uploaded_at=datetime.datetime.now(datetime.timezone.utc),
        status="pending_review",
    )
    session.add(price_list_import)
    session.flush()
    return price_list_import


def _make_entry(session, price_list_import, **overrides):
    defaults = dict(
        import_id=price_list_import.id,
        supplier_raw_name="Raw Name",
        price=10.0,
        currency="USD",
    )
    defaults.update(overrides)
    entry = PriceListEntry(**defaults)
    session.add(entry)
    session.flush()
    return entry


def test_apply_match_creates_new_price_version_and_upserts_alias(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    material = make_material()
    price_list_import = _make_import(session, supplier)
    entry = _make_entry(
        session, price_list_import, supplier_raw_name="ACME Screen", price=7.5
    )

    updated = apply_price_list_entry(
        session, price_list_import.id, entry.id, action="match", material_id=material.id
    )

    assert updated.action == "match"
    active_price = (
        session.query(Price)
        .filter(
            Price.material_id == material.id,
            Price.supplier_id == supplier.id,
            Price.valid_to.is_(None),
        )
        .one()
    )
    assert float(active_price.price) == 7.5
    assert active_price.source_import_id == price_list_import.id

    alias = (
        session.query(SupplierMaterialAlias)
        .filter_by(supplier_id=supplier.id, material_id=material.id)
        .one()
    )
    assert alias.supplier_raw_name == "ACME Screen"


def test_apply_match_closes_existing_active_price(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    material = make_material()
    old_price = Price(
        material_id=material.id,
        supplier_id=supplier.id,
        price=5.0,
        currency="USD",
        valid_from=datetime.date(2026, 1, 1),
        valid_to=None,
    )
    session.add(old_price)
    session.flush()

    price_list_import = _make_import(session, supplier)
    entry = _make_entry(session, price_list_import, price=6.0)

    apply_price_list_entry(
        session, price_list_import.id, entry.id, action="match", material_id=material.id
    )

    session.refresh(old_price)
    assert old_price.valid_to is not None

    active_prices = (
        session.query(Price)
        .filter(
            Price.material_id == material.id,
            Price.supplier_id == supplier.id,
            Price.valid_to.is_(None),
        )
        .all()
    )
    assert len(active_prices) == 1
    assert float(active_prices[0].price) == 6.0


def test_apply_match_does_not_duplicate_existing_alias(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    material = make_material()
    session.add(
        SupplierMaterialAlias(
            supplier_id=supplier.id,
            material_id=material.id,
            supplier_raw_name="Existing Alias Name",
        )
    )
    session.commit()

    price_list_import = _make_import(session, supplier)
    entry = _make_entry(
        session, price_list_import, supplier_raw_name="Existing Alias Name"
    )

    apply_price_list_entry(
        session, price_list_import.id, entry.id, action="match", material_id=material.id
    )

    aliases = (
        session.query(SupplierMaterialAlias)
        .filter_by(supplier_id=supplier.id, material_id=material.id)
        .all()
    )
    assert len(aliases) == 1


def test_apply_new_creates_material_alias_and_price_atomically(
    db_session, make_supplier
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    price_list_import = _make_import(session, supplier)
    entry = _make_entry(
        session, price_list_import, supplier_raw_name="Brand New Screen", price=12.0
    )

    with patch("app.price_ingestion.apply.embed_text", return_value=[0.1] * 1536):
        updated = apply_price_list_entry(
            session,
            price_list_import.id,
            entry.id,
            action="new",
            internal_sku="NEW-SKU-100",
            canonical_name="Brand New Screen",
        )

    assert updated.action == "new"
    material = session.query(Material).filter_by(internal_sku="NEW-SKU-100").one()
    assert material.embedding is not None

    alias = session.query(SupplierMaterialAlias).filter_by(material_id=material.id).one()
    assert alias.supplier_raw_name == "Brand New Screen"

    price = session.query(Price).filter_by(material_id=material.id).one()
    assert float(price.price) == 12.0


def test_apply_new_rolls_back_material_when_price_creation_fails(
    db_session, make_supplier
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    price_list_import = _make_import(session, supplier)
    entry = _make_entry(
        session, price_list_import, supplier_raw_name="Will Fail", price=9.0
    )

    with patch("app.price_ingestion.apply.embed_text", return_value=[0.1] * 1536):
        with patch(
            "app.price_ingestion.apply.Price",
            side_effect=IntegrityError("boom", None, Exception("boom")),
        ):
            with pytest.raises(IntegrityError):
                apply_price_list_entry(
                    session,
                    price_list_import.id,
                    entry.id,
                    action="new",
                    internal_sku="ROLLBACK-SKU",
                    canonical_name="Will Fail",
                )

    session.rollback()
    assert session.query(Material).filter_by(internal_sku="ROLLBACK-SKU").first() is None


def test_apply_raises_entry_not_found_for_unknown_entry(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    price_list_import = _make_import(session, supplier)

    with pytest.raises(EntryNotFoundError):
        apply_price_list_entry(
            session, price_list_import.id, uuid.uuid4(), action="match", material_id=uuid.uuid4()
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/price_ingestion/test_apply.py -v`
Expected: FAIL — `app.price_ingestion.apply` does not exist.

- [ ] **Step 3: Implement apply**

Create `backend/app/price_ingestion/apply.py`:

```python
"""Applying one reviewed PriceListEntry — see ADR-0019 §5. Each call is one
transaction: match closes the old active Price (if any) and upserts
SupplierMaterialAlias; new creates Material+Alias+Price together, rolling
back all three on any failure.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.models import Material, Price, PriceListEntry, SupplierMaterialAlias
from app.price_ingestion.embeddings import EmbeddingError, embed_text, material_embedding_input


class EntryNotFoundError(Exception):
    def __init__(self, import_id: uuid.UUID, entry_id: uuid.UUID):
        self.import_id = import_id
        self.entry_id = entry_id
        super().__init__(f"PriceListEntry {entry_id} not found in import {import_id}")


def _get_entry_or_raise(
    db: Session, import_id: uuid.UUID, entry_id: uuid.UUID
) -> PriceListEntry:
    entry = db.get(PriceListEntry, entry_id)
    if entry is None or entry.import_id != import_id:
        raise EntryNotFoundError(import_id, entry_id)
    return entry


def _upsert_alias(
    db: Session, supplier_id: uuid.UUID, material_id: uuid.UUID, raw_name: str
) -> None:
    existing = (
        db.query(SupplierMaterialAlias)
        .filter_by(supplier_id=supplier_id, material_id=material_id, supplier_raw_name=raw_name)
        .first()
    )
    if existing is None:
        db.add(
            SupplierMaterialAlias(
                supplier_id=supplier_id,
                material_id=material_id,
                supplier_raw_name=raw_name,
            )
        )


def _apply_match(
    db: Session, entry: PriceListEntry, supplier_id: uuid.UUID, material_id: uuid.UUID
) -> None:
    active_price = (
        db.query(Price)
        .filter(
            Price.material_id == material_id,
            Price.supplier_id == supplier_id,
            Price.valid_to.is_(None),
        )
        .first()
    )
    if active_price is not None:
        active_price.valid_to = datetime.date.today()

    new_price = Price(
        material_id=material_id,
        supplier_id=supplier_id,
        price=entry.price,
        currency=entry.currency,
        availability=entry.availability,
        min_order_qty=entry.min_order_qty,
        valid_from=datetime.date.today(),
        valid_to=None,
        source_import_id=entry.import_id,
    )
    db.add(new_price)
    _upsert_alias(db, supplier_id, material_id, entry.supplier_raw_name)

    entry.matched_material_id = material_id
    entry.action = "match"
    db.commit()


def _apply_new(
    db: Session,
    entry: PriceListEntry,
    supplier_id: uuid.UUID,
    internal_sku: str,
    canonical_name: str,
) -> None:
    material = Material(
        internal_sku=internal_sku,
        canonical_name=canonical_name,
        unit="unit",
        attributes={},
    )
    try:
        material.embedding = embed_text(material_embedding_input(canonical_name, {}))
    except EmbeddingError:
        material.embedding = None

    db.add(material)
    db.flush()

    _upsert_alias(db, supplier_id, material.id, entry.supplier_raw_name)

    price = Price(
        material_id=material.id,
        supplier_id=supplier_id,
        price=entry.price,
        currency=entry.currency,
        availability=entry.availability,
        min_order_qty=entry.min_order_qty,
        valid_from=datetime.date.today(),
        valid_to=None,
        source_import_id=entry.import_id,
    )
    db.add(price)

    entry.matched_material_id = material.id
    entry.action = "new"
    db.commit()


def apply_price_list_entry(
    db: Session,
    import_id: uuid.UUID,
    entry_id: uuid.UUID,
    *,
    action: Literal["match", "new", "skip"],
    material_id: uuid.UUID | None = None,
    internal_sku: str | None = None,
    canonical_name: str | None = None,
) -> PriceListEntry:
    """Applies one reviewed entry — see ADR-0019 §5. Raises EntryNotFoundError
    if the entry doesn't belong to this import. Any DB failure during
    action="new" rolls back Material+Alias+Price together (single
    transaction — no partial Material without its Price/Alias)."""
    entry = _get_entry_or_raise(db, import_id, entry_id)
    supplier_id = entry.import_.supplier_id

    if action == "skip":
        entry.action = "skip"
        db.commit()
        return entry

    try:
        if action == "match":
            assert material_id is not None
            _apply_match(db, entry, supplier_id, material_id)
        else:
            assert internal_sku is not None and canonical_name is not None
            _apply_new(db, entry, supplier_id, internal_sku, canonical_name)
    except Exception:
        db.rollback()
        raise

    db.refresh(entry)
    return entry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/price_ingestion/test_apply.py -v`
Expected: PASS

- [ ] **Step 5: Update the stale `PriceListEntry.action` docstring**

Edit `backend/app/models/price_list.py:52-53` — the existing docstring
says `update/new/ignore`, which predates this ADR and doesn't match the
verbs `apply.py` actually writes. Change:

```python
    action: Mapped[str | None] = mapped_column(String(20))
    """update/new/ignore — заполняется на экране ревью"""
```

to:

```python
    action: Mapped[str | None] = mapped_column(String(20))
    """match/new/skip — заполняется при применении строки на экране ревью,
    см. ADR-0019 §5. NULL = ещё не решено."""
```

- [ ] **Step 6: Run the full price_ingestion test suite once more**

Run: `cd backend && pytest tests/price_ingestion/test_apply.py -v`
Expected: PASS (docstring-only change, no behavior affected)

- [ ] **Step 7: Commit**

```bash
git add backend/app/price_ingestion/apply.py backend/app/models/price_list.py backend/tests/price_ingestion/test_apply.py
git commit -m "feat: add price-list entry apply service (ADR-0019 §5)"
```

---

### Task 9: Orchestration service + endpoints

**Files:**
- Create: `backend/app/price_ingestion/service.py`
- Create: `backend/app/api/schemas/price_ingestion.py`
- Create: `backend/app/api/price_ingestion.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/models/price_list.py` (add `not_applying` marker
  field — see step 3 note below)
- Create: `backend/alembic/versions/<hash>_add_not_applying_to_price_list_entries.py`
- Test: `backend/tests/price_ingestion/test_api.py`

**Interfaces:**
- Consumes: `extract_price_list_lines`, `validate_content_type`,
  `UnsupportedFileTypeError`, `PriceIngestionError` (Task 5);
  `match_price_list_lines`, `MatchedLine` (Task 7); `apply_price_list_entry`,
  `EntryNotFoundError` (Task 8).
- Produces: `ImportNotFoundError`, `create_price_list_import(db: Session,
  supplier_id: uuid.UUID, *, file_bytes: bytes, content_type: str,
  filename: str) -> PriceListImport`, `get_price_list_import(db: Session,
  import_id: uuid.UUID) -> PriceListImport` — used only by the endpoint
  layer (no further tasks depend on this module).

**Note on `PriceListEntry.not_applying`:** ADR-0019 §5 asks for "a field on
entry" to mark 'not applying now', explicitly leaving the exact design to
the implementer. The existing `action` column docstring already reserves
values `update/new/ignore`; reusing `action="ignore"` (rename to match
ADR-0019's actual verbs `match`/`new`/`skip` for consistency with Task 8)
means `action` alone distinguishes "not yet decided" (`NULL`) from
"explicitly skipped" (`"skip"`) from "applied" (`"match"`/`"new"`) — no
new column needed. Skip the migration/model-change step in this task and
rely on `action` as designed in Task 8.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/price_ingestion/test_api.py`:

```python
"""Tests for the price-list-import endpoints — see ADR-0019 §5.

The extraction + matching pipeline is always mocked at the service
boundary (match_price_list_lines) — these tests exercise routing, status
codes, and the transition to PriceListImport.status="approved", not model
accuracy (see docs/known-issues.md for that open item).
"""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import PriceListImport
from app.price_ingestion.extraction import ExtractedPriceLine
from app.price_ingestion.matching import MatchDecision, MatchedLine

client = TestClient(app)

FAKE_PDF_BYTES = b"%PDF-1.4 fake price list"


def _upload(supplier_id, content_type="application/pdf", data=FAKE_PDF_BYTES):
    return client.post(
        f"/suppliers/{supplier_id}/price-lists",
        files={"file": ("pricelist.pdf", data, content_type)},
    )


def _mock_pipeline(matched_lines):
    return patch(
        "app.price_ingestion.service.match_price_list_lines", return_value=matched_lines
    ), patch(
        "app.price_ingestion.service.extract_price_list_lines",
        return_value=[m.extracted for m in matched_lines],
    )


def test_upload_creates_import_and_entries(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Screen A", raw_sku=None, price=5.0, currency="USD",
                availability=None, min_order_qty=None,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.7,
                reasoning="no candidate close enough", suggested_internal_sku="SKU-A",
            ),
            embedding=[0.1] * 1536,
        )
    ]

    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        response = _upload(supplier.id)

    assert response.status_code == 201
    body = response.json()
    assert "import_id" in body
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["action"] is None
    assert entry["confidence"] == 0.7
    assert entry["suggested_internal_sku"] == "SKU-A"

    price_list_import = session.get(PriceListImport, uuid.UUID(body["import_id"]))
    assert price_list_import.status == "pending_review"


def test_get_import_returns_current_entries(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Screen B", raw_sku=None, price=8.0, currency="USD",
                availability=None, min_order_qty=None,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.6,
                reasoning="no match", suggested_internal_sku="SKU-B",
            ),
            embedding=[0.1] * 1536,
        )
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(supplier.id)
    import_id = upload_response.json()["import_id"]

    response = client.get(f"/price-list-imports/{import_id}")

    assert response.status_code == 200
    assert len(response.json()["entries"]) == 1


def test_apply_match_entry_updates_status_when_all_entries_resolved(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    material = make_material()

    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Known Screen", raw_sku=None, price=4.0, currency="USD",
                availability=None, min_order_qty=None,
            ),
            decision=MatchDecision(
                action="match", material_id=material.id, confidence=0.95,
                reasoning="matches", suggested_internal_sku=None,
            ),
            embedding=[0.1] * 1536,
        )
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(supplier.id)
    body = upload_response.json()
    import_id = body["import_id"]
    entry_id = body["entries"][0]["id"]

    response = client.post(
        f"/price-list-imports/{import_id}/entries/{entry_id}/apply",
        json={"action": "match", "material_id": str(material.id)},
    )

    assert response.status_code == 200

    session.expire_all()
    price_list_import = session.get(PriceListImport, uuid.UUID(import_id))
    assert price_list_import.status == "approved"


def test_apply_skip_leaves_import_pending_until_all_entries_resolved(
    db_session, make_supplier
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Line 1", raw_sku=None, price=1.0, currency="USD",
                availability=None, min_order_qty=None,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.5,
                reasoning="unsure", suggested_internal_sku="SKU-1",
            ),
            embedding=[0.1] * 1536,
        ),
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Line 2", raw_sku=None, price=2.0, currency="USD",
                availability=None, min_order_qty=None,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.5,
                reasoning="unsure", suggested_internal_sku="SKU-2",
            ),
            embedding=[0.1] * 1536,
        ),
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(supplier.id)
    body = upload_response.json()
    import_id = body["import_id"]
    entry_1_id = body["entries"][0]["id"]

    response = client.post(
        f"/price-list-imports/{import_id}/entries/{entry_1_id}/apply",
        json={"action": "skip"},
    )
    assert response.status_code == 200

    session.expire_all()
    price_list_import = session.get(PriceListImport, uuid.UUID(import_id))
    assert price_list_import.status == "pending_review"


def test_upload_rejects_unsupported_content_type(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    response = _upload(supplier.id, content_type="text/plain")

    assert response.status_code == 422


def test_upload_returns_404_for_unknown_supplier():
    with patch("app.price_ingestion.service.extract_price_list_lines", return_value=[]):
        response = _upload(uuid.uuid4())

    assert response.status_code == 404


def test_apply_returns_404_for_unknown_entry(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    matched = []
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(supplier.id)
    import_id = upload_response.json()["import_id"]

    response = client.post(
        f"/price-list-imports/{import_id}/entries/{uuid.uuid4()}/apply",
        json={"action": "skip"},
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/price_ingestion/test_api.py -v`
Expected: FAIL — none of the new modules/endpoints exist.

- [ ] **Step 3: Implement the orchestration service**

Create `backend/app/price_ingestion/service.py`:

```python
"""Orchestration for price-list upload — see ADR-0019 §5. Ties extraction
(step 1) + matching (step 2) together, creates PriceListImport and its
PriceListEntry rows, and answers "is this import fully resolved" for the
apply endpoint to decide when to flip status to "approved".
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy.orm import Session

from app.models import PriceListEntry, PriceListImport, Supplier
from app.price_ingestion.extraction import extract_price_list_lines
from app.price_ingestion.matching import match_price_list_lines

__all__ = [
    "ImportNotFoundError",
    "SupplierNotFoundError",
    "create_price_list_import",
    "get_price_list_import",
    "maybe_mark_import_approved",
]


class SupplierNotFoundError(Exception):
    def __init__(self, supplier_id: uuid.UUID):
        self.supplier_id = supplier_id
        super().__init__(f"Supplier {supplier_id} not found")


class ImportNotFoundError(Exception):
    def __init__(self, import_id: uuid.UUID):
        self.import_id = import_id
        super().__init__(f"PriceListImport {import_id} not found")


def create_price_list_import(
    db: Session,
    supplier_id: uuid.UUID,
    *,
    file_bytes: bytes,
    content_type: str,
    filename: str,
) -> PriceListImport:
    """Runs extraction + matching and persists one PriceListEntry per
    extracted line — see ADR-0019 §5. file_ref stores only the filename
    (the file itself is not persisted, same MVP choice as ADR-0018 §7)."""
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise SupplierNotFoundError(supplier_id)

    extracted = extract_price_list_lines(file_bytes=file_bytes, content_type=content_type)
    matched = match_price_list_lines(db, supplier_id, extracted)

    price_list_import = PriceListImport(
        supplier_id=supplier_id,
        file_ref=filename,
        uploaded_at=datetime.datetime.now(datetime.timezone.utc),
        status="pending_review",
        parsed_by_ai_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(price_list_import)
    db.flush()

    for index, line in enumerate(matched):
        entry = PriceListEntry(
            import_id=price_list_import.id,
            supplier_raw_name=line.extracted.raw_name,
            supplier_sku=line.extracted.raw_sku,
            matched_material_id=(
                line.decision.material_id if line.decision.action == "match" else None
            ),
            confidence=line.decision.confidence,
            reasoning=line.decision.reasoning,
            price=line.extracted.price,
            currency=line.extracted.currency,
            availability=line.extracted.availability,
            min_order_qty=line.extracted.min_order_qty,
            action=None,
        )
        db.add(entry)

    db.commit()
    db.refresh(price_list_import)
    return price_list_import


def get_price_list_import(db: Session, import_id: uuid.UUID) -> PriceListImport:
    price_list_import = db.get(PriceListImport, import_id)
    if price_list_import is None:
        raise ImportNotFoundError(import_id)
    return price_list_import


def maybe_mark_import_approved(db: Session, import_id: uuid.UUID) -> None:
    """Flips PriceListImport.status to "approved" once every entry has an
    explicit action (match/new/skip) — see ADR-0019 §5. Stays
    pending_review while any entry.action is still NULL."""
    price_list_import = get_price_list_import(db, import_id)
    unresolved = (
        db.query(PriceListEntry)
        .filter(PriceListEntry.import_id == import_id, PriceListEntry.action.is_(None))
        .count()
    )
    if unresolved == 0:
        price_list_import.status = "approved"
        db.commit()
```

- [ ] **Step 4: Schemas**

Create `backend/app/api/schemas/price_ingestion.py`:

```python
"""Pydantic schemas for price-list upload/review/apply — see ADR-0019 §5."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel


class PriceListEntryOut(BaseModel):
    id: uuid.UUID
    supplier_raw_name: str
    supplier_sku: str | None
    matched_material_id: uuid.UUID | None
    confidence: float | None
    reasoning: str | None
    price: float
    currency: str
    availability: int | None
    min_order_qty: int | None
    action: str | None
    suggested_internal_sku: str | None = None
    possible_duplicate_of: list[uuid.UUID] = []


class PriceListImportOut(BaseModel):
    import_id: uuid.UUID
    status: str
    entries: list[PriceListEntryOut]


class ApplyEntryIn(BaseModel):
    action: Literal["match", "new", "skip"]
    material_id: uuid.UUID | None = None
    internal_sku: str | None = None
    canonical_name: str | None = None
```

Note: `suggested_internal_sku`/`possible_duplicate_of` are not columns on
`PriceListEntry` (schema is frozen per Global Constraints) — the upload
endpoint fills them into the response from the in-memory `MatchedLine`
list at creation time only; `GET .../price-list-imports/{id}` (re-reading
after a page reload) cannot reconstruct them and returns `null`/`[]`. This
is an accepted MVP gap, not silently dropped — call it out explicitly in
the handoff message and record it in `docs/known-issues.md` (Task 10).

- [ ] **Step 5: Endpoints**

Create `backend/app/api/price_ingestion.py`:

```python
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.schemas.price_ingestion import (
    ApplyEntryIn,
    PriceListEntryOut,
    PriceListImportOut,
)
from app.core.database import get_db
from app.price_ingestion.apply import EntryNotFoundError, apply_price_list_entry
from app.price_ingestion.extraction import UnsupportedFileTypeError, validate_content_type
from app.price_ingestion.service import (
    ImportNotFoundError,
    SupplierNotFoundError,
    create_price_list_import,
    get_price_list_import,
    maybe_mark_import_approved,
)

router = APIRouter()

MAX_PRICE_LIST_FILE_SIZE = 10 * 1024 * 1024


def _to_import_out(price_list_import) -> PriceListImportOut:
    return PriceListImportOut(
        import_id=price_list_import.id,
        status=price_list_import.status,
        entries=[
            PriceListEntryOut(
                id=e.id,
                supplier_raw_name=e.supplier_raw_name,
                supplier_sku=e.supplier_sku,
                matched_material_id=e.matched_material_id,
                confidence=float(e.confidence) if e.confidence is not None else None,
                reasoning=e.reasoning,
                price=float(e.price),
                currency=e.currency,
                availability=e.availability,
                min_order_qty=e.min_order_qty,
                action=e.action,
            )
            for e in price_list_import.entries
        ],
    )


@router.post(
    "/suppliers/{supplier_id}/price-lists",
    response_model=PriceListImportOut,
    status_code=201,
)
async def upload_price_list(
    supplier_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> PriceListImportOut:
    """Multipart upload of a supplier price list — see ADR-0019 §5. Runs
    extraction + matching synchronously and returns the full set of
    PriceListEntry for the review screen. The file itself is not
    persisted (same MVP choice as ADR-0018 §7); only its filename is kept
    as PriceListImport.file_ref."""
    try:
        validate_content_type(file.content_type)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=422,
            detail="Неподдерживаемый тип файла — загрузите PDF или изображение (PNG/JPEG/WEBP).",
        ) from exc

    file_bytes = await file.read()
    if len(file_bytes) > MAX_PRICE_LIST_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Файл слишком большой (максимум 10MB).")

    try:
        price_list_import = create_price_list_import(
            db,
            supplier_id,
            file_bytes=file_bytes,
            content_type=file.content_type or "",
            filename=file.filename or "price-list",
        )
    except SupplierNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Supplier not found") from exc

    return _to_import_out(price_list_import)


@router.get("/price-list-imports/{import_id}", response_model=PriceListImportOut)
def get_price_list_import_endpoint(
    import_id: uuid.UUID, db: Session = Depends(get_db)
) -> PriceListImportOut:
    try:
        price_list_import = get_price_list_import(db, import_id)
    except ImportNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Price list import not found") from exc
    return _to_import_out(price_list_import)


@router.post(
    "/price-list-imports/{import_id}/entries/{entry_id}/apply",
    response_model=PriceListEntryOut,
)
def apply_entry(
    import_id: uuid.UUID,
    entry_id: uuid.UUID,
    payload: ApplyEntryIn,
    db: Session = Depends(get_db),
) -> PriceListEntryOut:
    try:
        entry = apply_price_list_entry(
            db,
            import_id,
            entry_id,
            action=payload.action,
            material_id=payload.material_id,
            internal_sku=payload.internal_sku,
            canonical_name=payload.canonical_name,
        )
    except EntryNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Price list entry not found") from exc

    maybe_mark_import_approved(db, import_id)
    db.refresh(entry)

    return PriceListEntryOut(
        id=entry.id,
        supplier_raw_name=entry.supplier_raw_name,
        supplier_sku=entry.supplier_sku,
        matched_material_id=entry.matched_material_id,
        confidence=float(entry.confidence) if entry.confidence is not None else None,
        reasoning=entry.reasoning,
        price=float(entry.price),
        currency=entry.currency,
        availability=entry.availability,
        min_order_qty=entry.min_order_qty,
        action=entry.action,
    )
```

Wire it into `backend/app/main.py` — add the import and
`app.include_router(...)` call:

```python
from app.api.price_ingestion import router as price_ingestion_router
```

```python
app.include_router(price_ingestion_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/price_ingestion/test_api.py -v`
Expected: PASS

- [ ] **Step 7: Run the full price_ingestion + material suite together**

Run: `cd backend && pytest tests/price_ingestion/ tests/material/ tests/scripts/ -v`
Expected: PASS (all tests across every task in this plan)

- [ ] **Step 8: Commit**

```bash
git add backend/app/price_ingestion/service.py backend/app/api/schemas/price_ingestion.py backend/app/api/price_ingestion.py backend/app/main.py backend/tests/price_ingestion/test_api.py
git commit -m "feat: add price-list import/apply endpoints (ADR-0019 §5)"
```

---

### Task 10: Full verification pass, docs, and known-issues entry

**Files:**
- Modify: `docs/known-issues.md` (create if it doesn't exist yet — check
  first with a Glob/Read; follow its existing entry format if present)
- Modify: `docs/data-model.md` (add `Material.embedding` + pgvector note,
  per ADR-0019 "Последствия")

**Interfaces:** none — this task is verification and documentation only.

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && pytest -v`
Expected: PASS — every test in the repo, not just the new ones (confirms
no regression in order_response_parser, allocation, purchase_record, etc.
from the `Material` model change).

- [ ] **Step 2: Run ruff**

Run: `cd backend && ruff check .`
Expected: no errors. Fix any lint issues found (import order, unused
imports, line length) before proceeding.

- [ ] **Step 3: Check/update `docs/known-issues.md`**

Read `docs/known-issues.md` if it exists (Glob first); if not, create it
following the plainest reasonable format (a markdown list of open items,
each with a one-line status). Add an entry:

```markdown
## ADR-0019 price-list ingestion — model accuracy unverified

Backend (extraction + matching pipeline, endpoints, apply-transaction
logic) is implemented and covered by mocked-LLM tests, but
OPENAI_PRICE_INGESTION_MODEL (`gpt-5.6-luna`, same default as
ADR-0018's order-response model) and the vector-search/matching prompt
have never been run against a real Screen Factory Florida supplier price
list. Mock tests verify the code paths, not model accuracy — same
distinction ADR-0018 draws for its own vision model. Needs: 3-5 real
supplier price-list documents (PDF and/or scanned) to validate extraction
completeness and match/new decision quality before this pipeline is used
on production data. DUPLICATE_DISTANCE_THRESHOLD
(`backend/app/price_ingestion/candidates.py`) is also an unvalidated
guess (0.15) pending real embeddings to tune against.

Also: `PriceListEntryOut.suggested_internal_sku`/`possible_duplicate_of`
are populated only in the upload response (computed in-memory at
extraction time) — they are not persisted on `PriceListEntry`, so
`GET /price-list-imports/{id}` (e.g. after a page reload) returns them as
null/empty. Acceptable for MVP per ADR-0019 (schema of PriceListEntry is
frozen this ADR), but the frontend review screen must not assume these
survive a reload without re-running extraction.
```

- [ ] **Step 4: Update `docs/data-model.md`**

Read the current `docs/data-model.md`, find the `Material` table
description/Mermaid ER diagram, and add a line noting the new `embedding
vector(1536)` nullable column with a short note: "pgvector extension,
used for price-list matching candidate search — see ADR-0019 §1. NULL
until backfilled or if the embeddings API was unavailable at
create/update time."

- [ ] **Step 5: Commit**

```bash
git add docs/known-issues.md docs/data-model.md
git commit -m "docs: record ADR-0019 model-accuracy open item and data-model update"
```

- [ ] **Step 6: Report to the user**

State explicitly (per the task instructions — do not skip silently):
backend implementation is complete and tested against mocked LLM/embedding
calls, but real accuracy on actual Screen Factory Florida supplier price
lists is unverified — same caveat ADR-0018 required for its vision model.
Ask whether the user can provide 1+ real price-list document now, or
confirm the `docs/known-issues.md` entry is sufficient to leave this open.

---

## Self-Review Notes

- **Spec coverage:** pgvector migration (Task 1), embeddings client (Task
  2), Material create/update graceful degradation (Task 3), backfill
  script (Task 4), extraction (Task 5), alias short-circuit + vector
  search (Task 6), LLM matching + duplicate detection (Task 7), apply
  transaction (Task 8), endpoints + orchestration (Task 9), docs/known-issues
  (Task 10) — every numbered item in the user's task list and ADR-0019 §1-5
  has a corresponding task.
- **Placeholder scan:** no TBD/TODO; every step has runnable code.
- **Type consistency:** `MatchDecision`, `MatchedLine`, `ExtractedPriceLine`
  field names are identical across Task 5/6/7/8/9 call sites.
  `PriceListEntry.action` values are consistently `"match" | "new" |
  "skip" | None` from Task 8 onward — the model's stale docstring
  (`update/new/ignore`, predating this ADR) is corrected in Task 8 Step 5
  to match.
