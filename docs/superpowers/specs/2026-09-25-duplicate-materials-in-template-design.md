# Спек: разрешить дубликаты материала в шаблоне проекта + подсветка

Связанный ADR: [`docs/decisions/0038-allow-duplicate-materials-in-template.md`](../../decisions/0038-allow-duplicate-materials-in-template.md).
Частично отменяет уникальность из ADR-0032 §1.

## Проблема

1. `ProjectTemplateItem` имеет уникальный индекс `(template_id, material_id)`.
   Повторное добавление того же материала в `TemplateItemsPanel` получает
   `409` от backend и не проходит.
2. Сопутствующий баг: `ProjectTemplatesPage.tsx` показывает на этот `409`
   неверный текст — "Шаблон с таким названием уже существует." — потому что
   единственный `ErrorBanner` страницы безусловно подставляет
   `conflictMessage` для любого 409, независимо от того, какое действие его
   вызвало.
3. Пользовательский запрос: не блокировать повтор, а подсвечивать обе
   строки как дубль (эта подсветка уже реализована в `TemplateItemsPanel`,
   но сейчас не может сработать на реальных данных, т.к. backend не даёт
   создать вторую строку).

## Объём

- Backend: снять уникальный индекс, убрать связанный с ним `409`-обработчик
  в `add_template_item`, миграция.
- Backend: `create_project` — без изменений (уже создаёт независимую
  строку `ProjectItem` на каждый `ProjectTemplateItem`), но добавить тест,
  фиксирующий это поведение при дублирующемся `material_id` в шаблоне.
- Frontend: `ProjectTemplatesPage.tsx` — `actionError` становится
  action-aware, `conflictMessage` применяется только к create/rename.
- Frontend: `TemplateItemsPanel.tsx` — без структурных изменений (подсветка
  дублей уже реализована), но существующий тест "does not block adding..."
  нужно расширить, чтобы он бил в реальный API-контракт (текущий тест мокает
  `onAddItem` напрямую и не проверяет, что панель верно рендерит ответ с
  двумя строками).
- Не в объёме: изменение семантики `quantity` в `ProjectTemplateItem` (её
  как не было, так и нет); подсветка дублей в `ProjectBuilderPage`/BOM
  проекта (явно исключено пользователем в предыдущей итерации).

## Backend

### 1. `backend/app/models/project_template.py`

Убрать `__table_args__` целиком (единственное его содержимое — снимаемый
индекс):

```python
class ProjectTemplateItem(UUIDPKMixin, Base):
    __tablename__ = "project_template_items"

    template_id: Mapped[uuid.UUID] = mapped_column(...)
    material_id: Mapped[uuid.UUID] = mapped_column(...)
    ...
```

### 2. Alembic-миграция

Новая ревизия (`alembic revision -m "drop uq_project_template_item"`),
голова текущей цепочки. Тело:

```python
def upgrade() -> None:
    op.drop_constraint(
        "uq_project_template_item", "project_template_items", type_="unique"
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_project_template_item",
        "project_template_items",
        ["template_id", "material_id"],
    )
```

(Если в БД к моменту отката уже есть дубликаты — `downgrade` упадёт на
создании constraint; это ожидаемо и не решается в рамках этой миграции,
как и для любой другой ADR-миграции, откатываемой на несовместимые данные.)

### 3. `backend/app/api/template.py` — `add_template_item`

Убрать `try/except IntegrityError` вокруг `db.commit()` (409 был специально
для снимаемого индекса; проверка `material_id` существует остаётся):

```python
@router.post("/{template_id}/items", response_model=ProjectTemplateOut, status_code=201)
def add_template_item(
    template_id: uuid.UUID, payload: ProjectTemplateItemCreate, db: Session = Depends(get_db)
) -> ProjectTemplateOut:
    template = _get_template_or_404(template_id, db)
    if db.get(Material, payload.material_id) is None:
        raise HTTPException(status_code=404, detail="Material not found")

    item = ProjectTemplateItem(template_id=template_id, material_id=payload.material_id)
    db.add(item)
    db.commit()

    template = _get_template_or_404(template_id, db)
    return _to_out(template)
```

`IntegrityError` import остаётся нужен для `create_template`/`rename_template`
(их собственный уникальный индекс на `name` не трогается) — не убирать
импорт целиком.

### 4. Тесты backend

`backend/tests/template/test_api.py` уже существует и **прямо тестирует
старое поведение**, которое эта ADR отменяет:

```python
def test_add_same_material_twice_returns_409_not_duplicate(
    db_session, make_template, make_material, make_user, make_session
):
    ...
    second = client.post(f"/project-templates/{template.id}/items", ...)
    assert second.status_code == 409
    ...
    assert count == 1
```

(`backend/tests/template/test_api.py:213-242`). Этот тест нужно **заменить**
(не добавить рядом) на тест, фиксирующий новое поведение:

```python
def test_add_same_material_twice_creates_second_item(
    db_session, make_template, make_material, make_user, make_session
):
    template = make_template()
    material = make_material()
    client = _admin_client(make_user, make_session)

    first = client.post(
        f"/project-templates/{template.id}/items",
        json={"material_id": str(material.id)},
        headers={"X-CSRF-Token": CSRF},
    )
    assert first.status_code == 201

    second = client.post(
        f"/project-templates/{template.id}/items",
        json={"material_id": str(material.id)},
        headers={"X-CSRF-Token": CSRF},
    )
    assert second.status_code == 201

    items = second.json()["items"]
    matching = [i for i in items if i["material_id"] == str(material.id)]
    assert len(matching) == 2
    assert matching[0]["id"] != matching[1]["id"]

    session, *_ = db_session
    from app.models import ProjectTemplateItem

    count = (
        session.query(ProjectTemplateItem)
        .filter_by(template_id=template.id, material_id=material.id)
        .count()
    )
    assert count == 2
```

`make_template`/`make_material`/`_admin_client` fixtures already exist in
`tests/template/conftest.py` — no fixture changes needed.

`tests/project/test_api.py` already covers template application
(`test_create_project_with_template_id_creates_matching_items`,
line 405, using `make_template(materials=[material_a, material_b])`).
Add one new test there, same style:

```python
def test_create_project_with_template_containing_duplicate_material(
    db_session, make_material, make_template, make_user, make_session
):
    session, project_ids, _material_ids, _supplier_ids, _user_ids, _template_ids = db_session
    material = make_material(canonical_name="Door Hinge")
    template = make_template(name="Two Hinges", materials=[material, material])
    client = _employee_client(make_user, make_session)

    response = client.post(
        "/projects",
        json={"title": "From Duplicate Template", "template_id": str(template.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 201
    body = response.json()
    project_ids.append(uuid.UUID(body["id"]))

    items = body["items"]
    assert len(items) == 2
    assert all(item["material_id"] == str(material.id) for item in items)
    assert all(item["quantity"] == 1 for item in items)
    assert items[0]["id"] != items[1]["id"]
```

(`make_template(materials=[material, material])` already works today
without any fixture change — `_make` just iterates the list and inserts
one `ProjectTemplateItem` per entry, duplicates included; it only failed at
the DB level via the constraint being removed here.)

## Frontend

### 1. `frontend/src/routes/ProjectTemplatesPage.tsx`

Заменить `actionError: unknown` на пару "источник + ошибка", чтобы баннер
знал, когда уместен `conflictMessage`:

```tsx
type ActionErrorSource = 'create' | 'rename' | 'addItem' | 'removeItem' | 'delete';

const [actionError, setActionError] = useState<{ source: ActionErrorSource; error: unknown } | null>(null);
```

Каждый `handle*` передаёт свой `source`:

```tsx
async function handleCreate(payload: { name: string }) {
  setActionError(null);
  try {
    await templatesApi.create(payload);
    closeCreate();
    await load();
  } catch (err) {
    setActionError({ source: 'create', error: err });
    throw err;
  }
}
```

(аналогично для `handleRename` → `'rename'`, `handleAddItem` → `'addItem'`,
`handleRemoveItem` → `'removeItem'`, `handleDelete` → `'delete'`; везде,
где сейчас `setActionError(err)` / `setActionError(null)`, — обновить
сигнатуру).

Рендер баннера:

```tsx
{actionError != null && (
  <ErrorBanner
    error={actionError.error}
    conflictMessage={
      actionError.source === 'create' || actionError.source === 'rename'
        ? 'Шаблон с таким названием уже существует.'
        : undefined
    }
  />
)}
```

`ErrorBanner.tsx` не меняется — `resolveMessage` уже корректно падает
обратно на `error.detail`, когда `conflictMessage` не передан (строка 24:
`if (error.status === 409 && conflictMessage)`).

### 2. `frontend/src/routes/templates/TemplateItemsPanel.tsx`

Без изменений кода — существующая группировка по категории и подсветка
дублей (`groupItemsByCategory`, `countByMaterialId`, `duplicateRow`,
бейдж "дубль") уже реализует нужное поведение; она становится действующей,
как только backend перестаёт блокировать вставку.

### 3. Тесты frontend

`TemplateItemsPanel.test.tsx` — существующий тест
"does not block adding a material already in the list, and highlights both
rows as duplicates" сейчас мокает `onAddItem` через `vi.fn().mockResolvedValue(undefined)`
и не проверяет рендер после ответа. Расширить: `onAddItem` должен вести
себя как реальный проп из `ProjectTemplatesPage` (обновляет `template.items`
после успеха) — либо переписать тест так, чтобы после клика "Добавить"
компонент получал обновлённый `template` (через `rerender`) с двумя
строками одного `material_id`, и проверить, что бейдж "дубль" появляется
на обеих. (Это по сути объединяется с уже существующим тестом
"marks two rows sharing a material_id as duplicates" — можно оставить как
есть, он уже покрывает рендер; смысл этого пункта — не тестировать заново
внутренний вызов `onAddItem` изолированно от результата, раз он теперь
реально может вернуть дубликат.)

Новый файл или блок в `ProjectTemplatesPage.test.tsx`:
- `addItemMock.mockRejectedValue(new ApiError(409, { detail: 'Material already in this template' }))`
  → баннер показывает "Material already in this template", **не**
  "Шаблон с таким названием уже существует.".
- `createMock.mockRejectedValue(new ApiError(409, { detail: 'Project template with this name already exists' }))`
  → баннер по-прежнему показывает "Шаблон с таким названием уже существует."
  (регрессия на существующее поведение create/rename).

## Порядок реализации

1. Backend: модель → миграция → эндпоинт → тесты backend (`pytest`).
2. Frontend: `ProjectTemplatesPage.tsx` action-aware error → тесты
   `ProjectTemplatesPage.test.tsx`.
3. Прогнать `TemplateItemsPanel.test.tsx` — должен остаться зелёным без
   изменений кода компонента; при необходимости поправить только тест.
4. `pytest`, `ruff check .`, `alembic upgrade head` (backend);
   `npm run lint`, `npm run test`, `npm run build` (frontend).
5. `docs/data-model.md:368-369` прямо утверждает снимаемую уникальность:
   "Уникальный индекс `(template_id, material_id)` — один материал не может
   входить в шаблон дважды." — заменить на предложение, отражающее ADR-0038
   (материал может входить в шаблон более одного раза; ссылка на ADR-0038
   рядом с существующей ссылкой на ADR-0032 в этом абзаце).
