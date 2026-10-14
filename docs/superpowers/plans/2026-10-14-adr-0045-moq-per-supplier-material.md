# ADR-0045: MOQ на связке поставщик+материал — план реализации

> **Для агентов-исполнителей:** ОБЯЗАТЕЛЬНЫЙ ПОДСКИЛЛ: используй superpowers:subagent-driven-development (рекомендуется) или superpowers:executing-plans, чтобы выполнять этот план задача-за-задачей. Шаги используют синтаксис чекбоксов (`- [ ]`) для отслеживания прогресса.

**Цель:** Включить минимальное количество заказа (`Price.min_order_qty`) в расчёт
ILP-аллокации (solver.py) так, чтобы: (1) solver считал реальную стоимость закупки
с учётом MOQ-излишка, а не цену за штуку × потребность; (2) пользователь явно видел
расхождение "нужно vs закажем"; (3) это никогда не доходило до текста ордера
поставщику.

**Архитектура:** `order_qty = max(потребность, MOQ)` считается как обычная
Python-константа на границе БД↔solver (в `service.py`, рядом с сегодняшним
`_to_cents`), **не** как новая переменная CP-SAT — one-hot-ограничение солвера
не меняется. Везде, где солвер сегодня умножает на `qty[m_id]` в контексте
конкретной пары (материал, поставщик), заменяем на `order_qty[(m,s)]`. Новое
поле `needed_quantity` (nullable, `NULL` = нет расхождения) добавляется на
`AllocationLine` и `OrderItem` по прецеденту ADR-0039 (`received_quantity`).

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic, OR-Tools CP-SAT, React/TypeScript.

**Spec:** `docs/decisions/0045-moq-per-supplier-material.md` (полный ADR — план
аргументирует от него, читай оба документа).

## Глобальные ограничения

- Денежная и количественная арифметика — только на backend, никогда на
  frontend (CLAUDE.md, принцип 4).
- `Price.min_order_qty` НЕ переименовывается (см. ADR-0045 §Решение/Модель
  данных) — имя поля остаётся как есть везде.
- `needed_quantity` — строго внутреннее поле. Никогда не должно попасть в
  текст ордера, уходящий поставщику (`buildOrderText`/`buildTargetPriceOrderText`).
- MOQ не должен становиться новым источником `INFEASIBLE` — единственный
  механизm влияния на допустимость пары — через `availability`-проверку (тот
  же механизм, что уже есть для обычной нехватки стока, ADR-0002).
- Деплой этого кода **на прод-БД заблокирован** до отдельного решения
  пользователя по фактическим значениям MOQ в проде (ADR-0045 §План выкатки
  п.3, статус на 2026-10-14). Эта задача реализует и тестирует код на dev —
  включение на проде не входит в объём этого плана.
- Каждая новая/изменённая функция в этом плане — через TDD (RED → GREEN),
  согласно CLAUDE.md "Тесты — обязательны для ILP allocation engine".
- Коммит — после каждой задачи (atomic commits), сообщение на английском по
  существующему стилю репозитория (`git log`), с атрибуцией Claude Sonnet 5.

## Review Focus

Пять классов входных данных/поведения, которые спецификация подразумевает,
но ни один тест явно не покрывает по умолчанию — не забыть сделать для них
тест внутри своей задачи:

1. **MOQ сильно больше потребности при настроенном `free_shipping_threshold`**
   — риск сломанной big-M линеаризации без явной ошибки модели (ADR-0045
   §Контекст, "главный технический риск"). Тест — Задача 3.
2. **MOQ у поставщика, но у него недостаточен `availability` относительно
   `order_qty` (не относительно исходной потребности)** — пара должна стать
   недопустимой, хотя по "наивной" проверке казалась бы достаточной. Тест —
   Задача 4.
3. **PDF-реимпорт без указанного MOQ в строке** не должен тихо затирать ранее
   сохранённый `Price.min_order_qty` в `NULL` — существующий дефект,
   фиксируемый в рамках этого ADR. Тест — Задача 8.
4. **Override строки на поставщика с другим MOQ** должен пересчитать и
   `quantity`, и `line_total`, не только `unit_price` — сегодня `quantity`
   не трогается при override вообще. Тест — Задача 9.
5. **`buildOrderText`/`buildTargetPriceOrderText` не должны содержать
   `needed_quantity`** ни в каком виде, даже когда он явно отличается от
   `quantity` — регрессионный тест именно на этот риск, не полагание на то,
   что никто не добавит поле туда случайно. Тест — Задача 13.

---

## Файловая карта

| Файл | Роль в этой задаче |
|---|---|
| `backend/app/allocation/types.py` | `PriceInput.order_qty` (новое поле), `AllocationLineResult.needed_quantity` (новое поле) |
| `backend/app/allocation/solver.py` | `order_total`/`max_order_total`/`price_terms` считаются от `order_qty[(m,s)]`, не `qty[m_id]`; фильтр availability по `order_qty` |
| `backend/app/allocation/preprocess.py` | `split_orphaned_materials` сравнивает `availability` с `order_qty`, не с потребностью |
| `backend/app/allocation/service.py` | сборка `order_qty` перед вызовом solver; `override_allocation_line_supplier` пересчитывает `quantity`/`needed_quantity`/`line_total` |
| `backend/app/allocation/order_service.py` | `find_replacement_candidates` — `availability_risk` от candidate-specific `order_qty`; перенос `needed_quantity` в `OrderItem` при создании ордера |
| `backend/app/price_ingestion/apply.py` | `_apply_match` наследует `min_order_qty` от закрываемой строки, если в новой выгрузке `None` |
| `backend/app/models/allocation.py` | `AllocationLine.needed_quantity` (новая колонка) |
| `backend/app/models/order.py` | `OrderItem.needed_quantity` (новая колонка) |
| `backend/app/api/schemas/allocation.py` | `AllocationLineOut.needed_quantity` |
| `backend/app/api/schemas/order.py` | `OrderItemOut.needed_quantity`, `PriceListEntryOut.current_active_min_order_qty` |
| `backend/app/api/order.py` | `_to_order_item_out` прокидывает `needed_quantity` |
| `backend/alembic/versions/<new>.py` | новая миграция: 2 nullable-колонки |
| `frontend/src/routes/AllocationResultPage.tsx` | предупреждение "заказано X вместо Y из-за MOQ" |
| `frontend/src/routes/OrderDetailPage.tsx` | то же для `OrderItem`; регрессионный тест на `buildOrderText` |
| `frontend/src/routes/.../PriceComparisonPage.tsx` | предупреждение у кандидата с MOQ выше потребности |
| `frontend/src/routes/.../PriceListImportReviewPage.tsx` | предупреждение "MOQ не указан в этой выгрузке, но был раньше" |

---

### Task 1: `order_qty`/`needed_quantity` в типах солвера

**Файлы:**
- Изменить: `backend/app/allocation/types.py`
- Тест: `backend/tests/allocation/test_solver.py`

**Интерфейсы:**
- Производит: `PriceInput.order_qty: int` (новое обязательное поле —
  вычисляется заранее, не `None`), `AllocationLineResult.needed_quantity: int`
  (новое обязательное поле на результате — `qty[m_id]`, исходная потребность).

Контекст: сегодня `PriceInput` (types.py:41-46) не содержит ни `order_qty`,
ни MOQ вообще — добавляем `order_qty`, вычисленный заранее (вызывающая сторона
отвечает за `max(потребность, MOQ)`, сам `PriceInput` просто носит готовое
число). `AllocationLineResult` (types.py:65-71) получает `needed_quantity` —
исходная потребность материала, независимо от того, что было заказано.

- [ ] **Шаг 1: Написать падающий тест**

```python
# backend/tests/allocation/test_solver.py — добавить в конец файла

def test_price_input_requires_order_qty_field():
    """order_qty — новое обязательное поле PriceInput (ADR-0045): нет
    default-значения, вызывающая сторона обязана посчитать
    max(потребность, MOQ) заранее."""
    price = PriceInput(
        material_id="m1",
        supplier_id="s1",
        unit_price_cents=500,
        availability=10,
        order_qty=10,
    )
    assert price.order_qty == 10


def test_allocation_line_result_carries_needed_quantity():
    """needed_quantity — исходная потребность материала, независимо от
    order_qty/quantity, который солвер реально выбрал для этой пары."""
    from app.allocation.types import AllocationLineResult

    line = AllocationLineResult(
        material_id="m1",
        supplier_id="s1",
        quantity=100,
        needed_quantity=37,
        unit_price_cents=500,
        line_total_cents=50000,
    )
    assert line.needed_quantity == 37
    assert line.quantity == 100
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Run: `cd backend && python -m pytest tests/allocation/test_solver.py::test_price_input_requires_order_qty_field tests/allocation/test_solver.py::test_allocation_line_result_carries_needed_quantity -v`
Ожидается: FAIL — `TypeError: __init__() got an unexpected keyword argument 'order_qty'` (и аналогично для `needed_quantity`).

- [ ] **Шаг 3: Минимальная реализация**

```python
# backend/app/allocation/types.py

@dataclass(frozen=True)
class PriceInput:
    material_id: str
    supplier_id: str
    unit_price_cents: int
    availability: int | None
    order_qty: int
    """max(потребность материала, Price.min_order_qty или 0) — считается
    заранее вызывающей стороной (service.py), до построения модели CP-SAT.
    Не None: всегда равен хотя бы потребности материала, если MOQ не задан
    или ниже неё. См. ADR-0045 §Решение/Solver."""
```

```python
# backend/app/allocation/types.py

@dataclass(frozen=True)
class AllocationLineResult:
    material_id: str
    supplier_id: str
    quantity: int
    needed_quantity: int
    """Исходная потребность материала (qty[m_id] на входе в солвер),
    независимо от того, что реально заказано (quantity, может быть выше
    из-за MOQ выбранного поставщика). См. ADR-0045."""
    unit_price_cents: int
    line_total_cents: int
```

- [ ] **Шаг 4: Убедиться, что тест проходит**

Run: `cd backend && python -m pytest tests/allocation/test_solver.py -v`
Ожидается: все тесты в файле падают с `TypeError` на недостающие аргументы
(`order_qty`/`needed_quantity`) у существующих construction sites —
это ожидаемо, их обновит Задача 2. Два новых теста из Шага 1 — PASS.

- [ ] **Шаг 5: Commit**

```bash
git add backend/app/allocation/types.py backend/tests/allocation/test_solver.py
git commit -m "feat(allocation): add order_qty/needed_quantity fields to solver types (ADR-0045)"
```

---

### Task 2: Солвер считает от `order_qty`, не от `qty[m_id]`

**Файлы:**
- Изменить: `backend/app/allocation/solver.py`
- Тест: `backend/tests/allocation/test_solver.py`

**Интерфейсы:**
- Потребляет: `PriceInput.order_qty` (Task 1), `AllocationLineResult.needed_quantity` (Task 1)
- Производит: `solve_allocation(data: AllocationInput) -> AllocationResult` — та же сигнатура, но `order_total`/`max_order_total`/`price_terms`/availability-фильтр теперь считаются от `order_qty[(m,s)]`.

Это самая рискованная задача плана — здесь живёт риск big-M линеаризации
(ADR-0045 §Контекст, последний абзац). Шаги написаны в порядке: сначала
регрессионные тесты на "MOQ не задан → поведение как раньше", потом тесты
на сам эффект MOQ, потом тест на big-M риск — каждый со своим RED/GREEN,
но реализация солвера меняется один раз (её нельзя сделать по кусочкам без
риска промежуточного несогласованного состояния модели).

- [ ] **Шаг 1: Написать падающие тесты**

```python
# backend/tests/allocation/test_solver.py — добавить в конец файла

def test_moq_not_set_behavior_unchanged():
    """order_qty == qty[m_id] на всех парах (MOQ не задан ни у кого) -> тот
    же результат, что без этого ADR. Регрессия на "ничего не ломаем, когда
    MOQ нет"."""
    materials = [MaterialInput(material_id="m1", quantity=10)]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=None)
    ]
    prices = [
        PriceInput(
            material_id="m1", supplier_id="s1", unit_price_cents=500,
            availability=100, order_qty=10,
        )
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status in ("OPTIMAL", "FEASIBLE")
    line = result.lines[0]
    assert line.quantity == 10
    assert line.needed_quantity == 10
    assert line.line_total_cents == 5000


def test_moq_below_demand_no_surplus():
    """Потребность (37) >= MOQ (10) -> order_qty == потребность, нет
    излишка. needed_quantity == quantity в этом случае (не тестируем здесь
    NULL-семантику needed_quantity на AllocationLine — это объект service.py,
    Task 5)."""
    materials = [MaterialInput(material_id="m1", quantity=37)]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=None)
    ]
    prices = [
        PriceInput(
            material_id="m1", supplier_id="s1", unit_price_cents=100,
            availability=100, order_qty=37,
        )
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    line = result.lines[0]
    assert line.quantity == 37
    assert line.needed_quantity == 37


def test_moq_above_demand_produces_surplus_in_quantity_and_cost():
    """Потребность 37, MOQ=100 у выбранного поставщика (единственного) ->
    AllocationLine.quantity == 100 (order_qty, не потребность),
    needed_quantity == 37, line_total считается от 100, не от 37 -- прямая
    регрессия против ошибки первой версии ADR (солвер считал от потребности)."""
    materials = [MaterialInput(material_id="m1", quantity=37)]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=None)
    ]
    prices = [
        PriceInput(
            material_id="m1", supplier_id="s1", unit_price_cents=100,
            availability=1000, order_qty=100,  # max(37, MOQ=100)
        )
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    line = result.lines[0]
    assert line.quantity == 100
    assert line.needed_quantity == 37
    assert line.line_total_cents == 100 * 100  # 100 центов * 100 шт


def test_moq_expensive_but_no_moq_supplier_beats_cheap_high_moq_supplier():
    """Поставщик A: дешевле за штуку (10 центов), но MOQ=1000 (потребность
    37 -> реально 1000 * 10 = 10000 центов). Поставщик B: дороже за штуку
    (50 центов), без MOQ (37 * 50 = 1850 центов). Солвер должен выбрать B,
    хотя его цена за штуку выше -- это и есть "честная экономика", которую
    просил пользователь (ADR-0045 §Решение/Solver)."""
    materials = [MaterialInput(material_id="m1", quantity=37)]
    suppliers = [
        SupplierInput(supplier_id="cheap_high_moq", flat_fee_cents=0, free_shipping_threshold_cents=None),
        SupplierInput(supplier_id="pricier_no_moq", flat_fee_cents=0, free_shipping_threshold_cents=None),
    ]
    prices = [
        PriceInput(
            material_id="m1", supplier_id="cheap_high_moq", unit_price_cents=10,
            availability=10000, order_qty=1000,
        ),
        PriceInput(
            material_id="m1", supplier_id="pricier_no_moq", unit_price_cents=50,
            availability=100, order_qty=37,
        ),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    line = result.lines[0]
    assert line.supplier_id == "pricier_no_moq"
    assert line.quantity == 37
    assert line.line_total_cents == 1850


def test_moq_availability_checked_against_order_qty_not_demand():
    """availability=50, order_qty=100 (MOQ=100, потребность=37) -> пара
    недопустима (50 < 100), хотя по потребности (37) availability казалось
    бы достаточным. Единственный поставщик материала -> материал уходит в
    NO_SOLVABLE_MATERIALS (через preprocess, здесь проверяем прямое
    поведение фильтра солвера на уровне "пара не входит в x")."""
    materials = [MaterialInput(material_id="m1", quantity=37)]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=None)
    ]
    prices = [
        PriceInput(
            material_id="m1", supplier_id="s1", unit_price_cents=100,
            availability=50, order_qty=100,
        )
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status == "INFEASIBLE"
    assert result.lines == []


def test_moq_much_larger_than_demand_does_not_break_free_shipping_bigm():
    """Прямой тест на риск из ADR-0045 §Контекст: MOQ намного больше
    потребности (потребность 1, MOQ 10000) у поставщика с настроенным
    free_shipping_threshold. max_order_total должен считаться от order_qty
    (10000 * 100 центов = 1_000_000), не от qty[m_id] (1 * 100 = 100) --
    иначе big_m = threshold + max_order_total окажется слишком маленьким
    относительно реального order_total, и линеаризация free[s]/z[s] может
    дать содержательно неверный (но математически допустимый) free_var.
    threshold=500_000 центов -- order_total (10000*100=1_000_000) ЕГО
    превышает, значит free_shipping_achieved должно быть True."""
    materials = [MaterialInput(material_id="m1", quantity=1)]
    suppliers = [
        SupplierInput(
            supplier_id="s1", flat_fee_cents=1000,
            free_shipping_threshold_cents=500_000,
        )
    ]
    prices = [
        PriceInput(
            material_id="m1", supplier_id="s1", unit_price_cents=100,
            availability=20000, order_qty=10000,
        )
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    line = result.lines[0]
    assert line.quantity == 10000
    assert line.line_total_cents == 1_000_000
    summary = result.supplier_summaries[0]
    assert summary.goods_total_cents == 1_000_000
    assert summary.free_shipping_achieved is True
    assert summary.delivery_fee_cents == 0
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Run: `cd backend && python -m pytest tests/allocation/test_solver.py -v -k "moq"`
Ожидается: FAIL на всех — солвер сегодня считает от `qty[m_id]`
(исходная потребность), игнорируя `order_qty` полностью (поле есть в
`PriceInput`, но solver.py его не читает).

- [ ] **Шаг 3: Реализация — заменить `qty[m_id]` на `order_qty[(m,s)]` везде, где это про конкретную пару**

```python
# backend/app/allocation/solver.py — полная замена функции solve_allocation

def solve_allocation(data: AllocationInput) -> AllocationResult:
    if not data.materials:
        return AllocationResult(status="NO_SOLVABLE_MATERIALS")

    qty = {m.material_id: m.quantity for m in data.materials}
    material_ids = list(qty.keys())

    # price[m][s] и order_qty[m][s] -- только для допустимых пар.
    # availability сравнивается с order_qty (заказываем), не с qty
    # (потребность) -- ADR-0045: поставщик с MOQ=100 и availability=50 не
    # должен считаться достаточным для потребности 37, потому что реально
    # закажут 100, а в наличии только 50.
    price: dict[tuple[str, str], int] = {}
    order_qty: dict[tuple[str, str], int] = {}
    for p in data.prices:
        if p.material_id not in qty:
            continue
        if p.availability is not None and p.availability < p.order_qty:
            continue
        price[(p.material_id, p.supplier_id)] = p.unit_price_cents
        order_qty[(p.material_id, p.supplier_id)] = p.order_qty

    suppliers_by_id = {s.supplier_id: s for s in data.suppliers}
    supplier_ids = sorted({s for (_, s) in price})

    model = cp_model.CpModel()

    # Переменные x[m][s].
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    for m_id in material_ids:
        for s_id in supplier_ids:
            if (m_id, s_id) in price:
                x[(m_id, s_id)] = model.new_bool_var(f"x_{m_id}_{s_id}")

    # Ограничение 1: назначение -- ровно один поставщик на материал.
    # Не меняется ADR-0045: MOQ не делает пару недопустимой по этому
    # ограничению, только через availability-фильтр выше.
    for m_id in material_ids:
        candidates = [x[(m_id, s_id)] for s_id in supplier_ids if (m_id, s_id) in x]
        model.add(sum(candidates) == 1)

    # ADR-0028 §1/§2, ADR-0034 §3 -- без изменений, завязано только на x.
    materials_by_category: dict[str, list[str]] = {}
    for m in data.materials:
        if m.requires_single_supplier and m.category_id is not None:
            materials_by_category.setdefault(m.category_id, []).append(m.material_id)

    diff: dict[tuple[str, str], cp_model.IntVar] = {}
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

    # Переменные y[s].
    y: dict[str, cp_model.IntVar] = {s_id: model.new_bool_var(f"y_{s_id}") for s_id in supplier_ids}

    # Ограничение 3: активация поставщика.
    for (_m_id, s_id), var in x.items():
        model.add(var <= y[s_id])

    # order_total[s] = Σ_m x[m][s] * price[m][s] * order_qty[m][s].
    # ADR-0045: раньше умножалось на qty[m_id] (потребность) -- теперь на
    # order_qty[(m,s)] (заказываем, с учётом MOQ-излишка этой конкретной
    # пары). max_order_total[s_id] -- верхняя граница для big-M
    # линеаризации free[s]/z[s] ниже -- ОБЯЗАНА считаться от той же
    # величины (order_qty), иначе при большом MOQ она окажется заниженной
    # относительно order_total[s] и сломает линеаризацию без видимой
    # ошибки (см. test_moq_much_larger_than_demand_does_not_break_free_shipping_bigm).
    order_total: dict[str, cp_model.LinearExpr] = {}
    max_order_total: dict[str, int] = {}
    for s_id in supplier_ids:
        terms = [
            x[(m_id, s_id)] * price[(m_id, s_id)] * order_qty[(m_id, s_id)]
            for m_id in material_ids
            if (m_id, s_id) in x
        ]
        order_total[s_id] = sum(terms)
        max_order_total[s_id] = sum(
            price[(m_id, s_id)] * order_qty[(m_id, s_id)]
            for m_id in material_ids
            if (m_id, s_id) in x
        )

    # Ограничение 4: минимальная сумма заказа (опционально). Без изменений
    # по формуле -- order_total[s] уже включает MOQ-излишек.
    for s_id in supplier_ids:
        min_amount = suppliers_by_id[s_id].per_order_min_amount_cents
        if min_amount > 0:
            model.add(order_total[s_id] >= min_amount * y[s_id])

    # free[s] и big-M linking для free_shipping_threshold. Без изменений
    # по формуле -- max_order_total уже пересчитан выше от order_qty.
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

    # Целевая функция. price_terms теперь от order_qty, не qty[m_id] --
    # ADR-0045: солвер должен минимизировать реальную стоимость закупки
    # (цена * фактически заказываемое количество), иначе недооценивает
    # дорогих по факту поставщиков с большим MOQ.
    price_terms = [
        x[(m_id, s_id)] * price[(m_id, s_id)] * order_qty[(m_id, s_id)]
        for (m_id, s_id) in x
    ]
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
            quantity = order_qty[(m_id, s_id)]
            lines.append(
                AllocationLineResult(
                    material_id=m_id,
                    supplier_id=s_id,
                    quantity=quantity,
                    needed_quantity=qty[m_id],
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

- [ ] **Шаг 4: Убедиться, что тесты проходят**

Run: `cd backend && python -m pytest tests/allocation/test_solver.py -v`
Ожидается: PASS на всех тестах файла (включая старые — `order_qty` теперь
читается, но в старых тестах `order_qty == qty[m_id]`, то есть поведение
не меняется).

- [ ] **Шаг 5: Commit**

```bash
git add backend/app/allocation/solver.py backend/tests/allocation/test_solver.py
git commit -m "feat(allocation): solver computes cost/availability from order_qty, not demand (ADR-0045)"
```

---

### Task 3: `requires_single_supplier` и неактивный поставщик — регрессия взаимодействия с MOQ

**Файлы:**
- Тест: `backend/tests/allocation/test_solver.py`

**Интерфейсы:**
- Потребляет: `solve_allocation` (Task 2) как есть, без изменений кода.

Это задача только из тестов — подтверждает, что ADR-0028 (строгая категория)
и big-M риск не взаимодействуют с MOQ непредсказуемо. Код solver.py уже
корректен после Task 2 — здесь просто закрываем Review Focus п.1 вторым
углом (категория + MOQ одновременно).

- [ ] **Шаг 1: Написать падающий тест (если он ещё не покрыт) и подтверждающий тест**

```python
# backend/tests/allocation/test_solver.py — добавить в конец файла

def test_moq_interaction_with_requires_single_supplier():
    """Строгая категория (ADR-0028) плюс MOQ-излишек у одного из
    поставщиков категории -- мягкий штраф за разброс считается как обычно
    (от x, не от количества), не ломается наличием MOQ."""
    materials = [
        MaterialInput(
            material_id="m1", quantity=10, category_id="cat1",
            requires_single_supplier=True,
        ),
        MaterialInput(
            material_id="m2", quantity=5, category_id="cat1",
            requires_single_supplier=True,
        ),
    ]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=100, free_shipping_threshold_cents=None),
        SupplierInput(supplier_id="s2", flat_fee_cents=100, free_shipping_threshold_cents=None),
    ]
    prices = [
        # s1 дешевле на m1, но дороже на m2 из-за MOQ -- проверяем, что
        # решение остаётся OPTIMAL/FEASIBLE, не ломается математически.
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=10, availability=100, order_qty=10),
        PriceInput(material_id="m2", supplier_id="s1", unit_price_cents=10, availability=100, order_qty=50),  # MOQ=50
        PriceInput(material_id="m1", supplier_id="s2", unit_price_cents=15, availability=100, order_qty=10),
        PriceInput(material_id="m2", supplier_id="s2", unit_price_cents=15, availability=100, order_qty=5),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.lines) == 2


def test_moq_interaction_with_inactive_supplier_filtered_before_reaching_solver():
    """Поставщик, неактивный для аллокации (ADR-0041), не должен появиться
    в supplier_ids вообще -- это ответственность service.py (фильтрует
    price_inputs до вызова solve_allocation), не solver.py. Здесь
    подтверждаем, что solve_allocation сам по себе не делает собственной
    проверки активности -- raw PriceInput без такого флага всегда
    учитывается, порядок фильтров (активность, потом MOQ) живёт в
    service.py, см. Task 5."""
    materials = [MaterialInput(material_id="m1", quantity=10)]
    suppliers = [
        SupplierInput(supplier_id="s1", flat_fee_cents=0, free_shipping_threshold_cents=None)
    ]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=10, availability=100, order_qty=100),
    ]

    result = solve_allocation(
        AllocationInput(materials=materials, suppliers=suppliers, prices=prices)
    )

    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.lines[0].quantity == 100
```

- [ ] **Шаг 2: Запустить тесты — должны сразу проходить (это регрессионное подтверждение, не новая логика)**

Run: `cd backend && python -m pytest tests/allocation/test_solver.py -v -k "interaction"`
Ожидается: PASS сразу (Task 2 уже реализовала нужную логику) — если
какой-то тест падает, значит Task 2 реализована неверно, вернуться туда.

- [ ] **Шаг 3: Commit**

```bash
git add backend/tests/allocation/test_solver.py
git commit -m "test(allocation): MOQ interaction with strict categories and supplier filtering (ADR-0045)"
```

---

### Task 4: `split_orphaned_materials` сравнивает с `order_qty`, не с потребностью

**Файлы:**
- Изменить: `backend/app/allocation/preprocess.py`
- Тест: `backend/tests/allocation/test_preprocess.py`

**Интерфейсы:**
- Потребляет: `PriceInput.order_qty` (Task 1)
- Производит: `split_orphaned_materials(materials, prices) -> tuple[list[MaterialInput], list[OrphanedMaterial]]` — та же сигнатура, но сравнение `availability` теперь против готового `price.order_qty`, а не `material.quantity`.

Контекст: сегодня (preprocess.py:27-29) `has_sufficient` сравнивает
`price.availability` с `material.quantity` (исходной потребностью) — это
пропускает случай "у поставщика MOQ=100, availability=50, достаточно для
потребности 37, но реально закажут 100, а в наличии только 50". После этой
задачи сравнение идёт с `price.order_qty`, который уже содержит `max(demand, moq)`
на уровне каждой конкретной цены (вычисляется заранее в service.py — см.
Task 5 — поэтому `preprocess.py` сам по себе не считает MOQ, только читает
уже готовое поле `order_qty` из `PriceInput`).

- [ ] **Шаг 1: Прочитать текущий тестовый файл, чтобы не продублировать существующие тесты**

Run: `cd backend && cat tests/allocation/test_preprocess.py`

- [ ] **Шаг 2: Написать падающий тест**

```python
# backend/tests/allocation/test_preprocess.py — добавить в конец файла

def test_moq_availability_checked_against_order_qty_not_demand():
    """availability=50, order_qty=100 (MOQ=100), потребность=37 -> материал
    должен попасть в orphaned, хотя по "наивному" сравнению с потребностью
    (37) availability казалось бы достаточным. Прямая регрессия против
    упущения первой версии ADR-0045 (см. §Контекст)."""
    materials = [MaterialInput(material_id="m1", quantity=37)]
    prices = [
        PriceInput(
            material_id="m1", supplier_id="s1", unit_price_cents=100,
            availability=50, order_qty=100,
        )
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert solvable == []
    assert len(orphaned) == 1
    assert orphaned[0].material_id == "m1"
    assert orphaned[0].required_quantity == 37


def test_moq_all_suppliers_insufficient_availability_material_orphaned():
    """Ни у одного поставщика материала availability >= order_qty -> материал
    в orphaned; другие материалы (не показаны здесь, но подразумевается на
    уровне solve_allocation после preprocessing) не затрагиваются."""
    materials = [MaterialInput(material_id="m1", quantity=10)]
    prices = [
        PriceInput(material_id="m1", supplier_id="s1", unit_price_cents=100, availability=5, order_qty=50),
        PriceInput(material_id="m1", supplier_id="s2", unit_price_cents=120, availability=3, order_qty=50),
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert solvable == []
    assert len(orphaned) == 1
    # best_partial -- наибольшая частичная поставка среди вариантов (s1=5 > s2=3)
    assert orphaned[0].best_partial_supplier_id == "s1"
    assert orphaned[0].best_partial_available == 5


def test_moq_sufficient_availability_against_order_qty_keeps_material_solvable():
    """availability >= order_qty (не только >= потребности) -> материал
    остаётся решаемым, как и раньше в обычном случае без MOQ."""
    materials = [MaterialInput(material_id="m1", quantity=37)]
    prices = [
        PriceInput(
            material_id="m1", supplier_id="s1", unit_price_cents=100,
            availability=150, order_qty=100,
        )
    ]

    solvable, orphaned = split_orphaned_materials(materials, prices)

    assert len(solvable) == 1
    assert orphaned == []
```

- [ ] **Шаг 3: Убедиться, что тесты падают**

Run: `cd backend && python -m pytest tests/allocation/test_preprocess.py -v -k "moq"`
Ожидается: FAIL на первом тесте — сегодняшний код сравнивает с
`material.quantity` (37), для которого availability=50 выглядит достаточным,
значит материал попадёт в `solvable`, а тест ожидает `orphaned`.

- [ ] **Шаг 4: Реализация**

```python
# backend/app/allocation/preprocess.py — полная замена содержимого функции split_orphaned_materials

def split_orphaned_materials(
    materials: list[MaterialInput],
    prices: list[PriceInput],
) -> tuple[list[MaterialInput], list[OrphanedMaterial]]:
    prices_by_material: dict[str, list[PriceInput]] = {}
    for price in prices:
        prices_by_material.setdefault(price.material_id, []).append(price)

    solvable: list[MaterialInput] = []
    orphaned: list[OrphanedMaterial] = []

    for material in materials:
        candidate_prices = prices_by_material.get(material.material_id, [])
        # ADR-0045: сравниваем с order_qty этой конкретной пары (уже
        # включает MOQ-излишек, max(потребность, MOQ)), не с исходной
        # потребностью material.quantity -- поставщик с MOQ выше того, что
        # у него физически есть в наличии, не должен считаться достаточным
        # просто потому что наличие покрывает исходную (меньшую) потребность.
        has_sufficient = any(
            price.availability is None or price.availability >= price.order_qty
            for price in candidate_prices
        )
        if has_sufficient:
            solvable.append(material)
            continue

        best_partial = _best_partial_offer(candidate_prices)
        orphaned.append(
            OrphanedMaterial(
                material_id=material.material_id,
                required_quantity=material.quantity,
                best_partial_supplier_id=best_partial.supplier_id if best_partial else None,
                best_partial_available=best_partial.availability if best_partial else None,
            )
        )

    return solvable, orphaned


def _best_partial_offer(prices: list[PriceInput]) -> PriceInput | None:
    partial_offers = [
        price for price in prices if price.availability is not None and price.availability > 0
    ]
    if not partial_offers:
        return None
    return max(partial_offers, key=lambda price: price.availability)
```

- [ ] **Шаг 5: Убедиться, что тесты проходят**

Run: `cd backend && python -m pytest tests/allocation/test_preprocess.py -v`
Ожидается: PASS на всех тестах файла.

- [ ] **Шаг 6: Commit**

```bash
git add backend/app/allocation/preprocess.py backend/tests/allocation/test_preprocess.py
git commit -m "fix(allocation): split_orphaned_materials compares availability against order_qty (ADR-0045)"
```

---

### Task 5: Миграция БД — `needed_quantity` на `AllocationLine`/`OrderItem`

**Файлы:**
- Изменить: `backend/app/models/allocation.py`
- Изменить: `backend/app/models/order.py`
- Создать: `backend/alembic/versions/<revision>_add_needed_quantity_to_allocation_line_and_order_item.py`
- Тест: `backend/tests/allocation/test_migration_needed_quantity.py` (новый файл)

**Интерфейсы:**
- Производит: `AllocationLine.needed_quantity: int | None` (ORM), `OrderItem.needed_quantity: int | None` (ORM), alembic revision с `upgrade()`/`downgrade()`.

Контекст: по прецеденту ADR-0039 (`received_quantity`) — `NULL` = нет
расхождения (MOQ не действовал или не был задан), не `0`. Без backfill —
старые строки остаются `NULL`.

- [ ] **Шаг 1: Узнать текущий alembic head перед созданием новой ревизии**

Run: `cd backend && alembic heads`
Ожидается: `c7f2a91b4e0d (head)` (подтверждено аудитом от 2026-10-14 — если
к моменту исполнения этого плана head изменился, использовать актуальный
head как `down_revision` новой ревизии вместо захардкоженного ниже).

- [ ] **Шаг 2: Добавить поля в ORM-модели**

```python
# backend/app/models/allocation.py -- внутри класса AllocationLine, после существующих полей,
# непосредственно перед overridden_at (логическая группа "план vs факт")

    needed_quantity: Mapped[int | None] = mapped_column()
    """Исходная потребность материала (MaterialInput.quantity на момент
    расчёта), когда она отличается от quantity (реально заказываемого) из-за
    MOQ выбранного поставщика. NULL = MOQ не действовал (quantity ==
    потребность) -- тот же принцип "NULL = нет особого случая", что у
    OrderItem.received_quantity (ADR-0039). См. ADR-0045."""
```

```python
# backend/app/models/order.py -- внутри класса OrderItem, после quantity, перед received_quantity

    needed_quantity: Mapped[int | None] = mapped_column()
    """Перенесено из AllocationLine.needed_quantity при создании OrderItem
    без изменений -- см. ADR-0045. NULL = MOQ не действовал на момент
    расчёта (quantity == исходная потребность)."""
```

- [ ] **Шаг 3: Написать падающий тест на существование колонок (прежде чем писать саму миграцию — TDD на уровне "миграция ещё не применена")**

```python
# backend/tests/allocation/test_migration_needed_quantity.py (новый файл)
"""Проверка одной конкретной alembic-ревизии (needed_quantity на
AllocationLine/OrderItem, ADR-0045) через прямой вызов модульных функций
upgrade()/downgrade() внутри транзакции теста, откатываемой в finally --
тот же паттерн, что test_order_item_migration.py (ADR-0033), после
инцидента ADR-0034 с живым alembic против общей dev-БД (см.
docs/known-issues.md, "ИНЦИДЕНТ"). НИКОГДА не вызывает
alembic.command.upgrade/downgrade напрямую против общей БД.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

REVISION_FILE = "REPLACE_WITH_ACTUAL_FILENAME_add_needed_quantity_to_allocation_line_and_order_item.py"


def _load_migration_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / REVISION_FILE
    )
    spec = importlib.util.spec_from_file_location("needed_quantity_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_adds_nullable_columns_without_touching_existing_rows(db_session):
    session, *_ = db_session
    module = _load_migration_module()
    connection = session.connection()
    ctx = MigrationContext.configure(connection)
    op = Operations(ctx)

    # Предварительно удостовериться, что колонок ещё нет (на случай, если
    # модель уже содержит их через предыдущий тест-ран в этой же БД) --
    # пропустить добавление, если уже существуют, чтобы тест был
    # идемпотентным при повторном запуске.
    inspector = sa.inspect(connection)
    existing_cols = {c["name"] for c in inspector.get_columns("allocation_lines")}
    if "needed_quantity" in existing_cols:
        session.rollback()
        return

    module.upgrade()
    connection = session.connection()
    inspector = sa.inspect(connection)
    allocation_line_cols = {c["name"] for c in inspector.get_columns("allocation_lines")}
    order_item_cols = {c["name"] for c in inspector.get_columns("order_items")}
    assert "needed_quantity" in allocation_line_cols
    assert "needed_quantity" in order_item_cols

    session.rollback()  # никогда не коммитим DDL теста на общую dev-БД


def test_downgrade_removes_columns(db_session):
    session, *_ = db_session
    module = _load_migration_module()
    connection = session.connection()
    ctx = MigrationContext.configure(connection)
    op = Operations(ctx)

    module.upgrade()
    module.downgrade()

    inspector = sa.inspect(connection)
    allocation_line_cols = {c["name"] for c in inspector.get_columns("allocation_lines")}
    order_item_cols = {c["name"] for c in inspector.get_columns("order_items")}
    assert "needed_quantity" not in allocation_line_cols
    assert "needed_quantity" not in order_item_cols

    session.rollback()
```

- [ ] **Шаг 4: Создать файл миграции (имя генерирует сам alembic — обновить `REVISION_FILE` в тесте после этого шага)**

Run: `cd backend && alembic revision -m "add needed_quantity to allocation_line and order_item"`

Открыть созданный файл и заменить его содержимое:

```python
"""add needed_quantity to allocation_line and order_item

Revision ID: <сгенерированный alembic>
Revises: c7f2a91b4e0d
Create Date: <сгенерированная alembic>

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "<сгенерированный alembic>"
down_revision: str | None = "c7f2a91b4e0d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("allocation_lines", sa.Column("needed_quantity", sa.Integer(), nullable=True))
    op.add_column("order_items", sa.Column("needed_quantity", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("order_items", "needed_quantity")
    op.drop_column("allocation_lines", "needed_quantity")
```

Обновить `REVISION_FILE` в `test_migration_needed_quantity.py` на реальное
имя созданного файла (например
`"0a1b2c3d4e5f_add_needed_quantity_to_allocation_line_and_order_item.py"`).

- [ ] **Шаг 5: Применить миграцию на dev-БД и прогнать тесты**

Run: `cd backend && alembic upgrade head`
Run: `cd backend && python -m pytest tests/allocation/test_migration_needed_quantity.py -v`
Ожидается: PASS. Первый тест увидит, что колонки уже существуют (применены
через `alembic upgrade head` только что), пропустит повторное добавление и
просто подтвердит их наличие.

- [ ] **Шаг 6: Прогнать полный набор тестов `tests/allocation/` — убедиться, что новые nullable-колонки не сломали существующие ORM-конструкторы**

Run: `cd backend && python -m pytest tests/allocation/ -q`
Ожидается: PASS (новые колонки nullable, существующий код их не передаёт — ORM сама подставит NULL).

- [ ] **Шаг 7: Commit**

```bash
git add backend/app/models/allocation.py backend/app/models/order.py backend/alembic/versions/*_add_needed_quantity_to_allocation_line_and_order_item.py backend/tests/allocation/test_migration_needed_quantity.py
git commit -m "feat(db): add nullable needed_quantity column to AllocationLine/OrderItem (ADR-0045)"
```

---

### Task 6: `service.py` считает `order_qty` перед вызовом солвера, сохраняет `needed_quantity`

**Файлы:**
- Изменить: `backend/app/allocation/service.py`
- Тест: `backend/tests/allocation/test_service.py`

**Интерфейсы:**
- Потребляет: `PriceInput.order_qty` (Task 1), `AllocationLineResult.needed_quantity` (Task 1), `solve_allocation` (Task 2), `AllocationLine.needed_quantity` (Task 5)
- Производит: `run_allocation(db, project_id) -> AllocationRun` — та же сигнатура, но персистирует `AllocationLine.needed_quantity` (только когда отличается от `quantity`, иначе `NULL`).

- [ ] **Шаг 1: Написать падающие тесты**

```python
# backend/tests/allocation/test_service.py — добавить в конец файла

def test_run_allocation_persists_needed_quantity_when_moq_creates_surplus(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Потребность 37, единственный поставщик с min_order_qty=100 ->
    AllocationLine.quantity == 100, needed_quantity == 37, line_total
    считается от 100 * price."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=1.00, availability=1000, min_order_qty=100)
    project = make_project([(material, 37)])

    run = run_allocation(session, project.id)

    assert run.status == "ok"
    line = run.lines[0]
    assert line.quantity == 100
    assert line.needed_quantity == 37
    assert float(line.line_total) == 100.00


def test_run_allocation_leaves_needed_quantity_null_when_moq_not_exceeded(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Потребность (200) >= MOQ (100) -> needed_quantity остаётся NULL (не
    0 и не равно quantity явно записанным числом) -- поведение не
    отличается от "MOQ не было" на уровне хранения."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=1.00, availability=1000, min_order_qty=100)
    project = make_project([(material, 200)])

    run = run_allocation(session, project.id)

    line = run.lines[0]
    assert line.quantity == 200
    assert line.needed_quantity is None


def test_run_allocation_moq_surplus_included_in_per_order_min_amount(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Ограничение 4 (per_order_min_amount) считается от order_total,
    включающего MOQ-излишек -- поставщик, который без учёта излишка не
    набирал бы минимум заказа, с учётом излишка набирает его."""
    session, *_ = db_session
    supplier = make_supplier(
        flat_fee=0.0, free_shipping_threshold=0.0, per_order_min_amount=50.0,
    )
    material = make_material()
    # потребность 1 * 1.00 = 1.00 (ниже минимума 50), но MOQ=100 -> order_qty=100
    # -> order_total = 100 * 1.00 = 100.00 (выше минимума 50) -> остаётся FEASIBLE,
    # не INFEASIBLE.
    make_price(material, supplier, price=1.00, availability=1000, min_order_qty=100)
    project = make_project([(material, 1)])

    run = run_allocation(session, project.id)

    assert run.status == "ok"
    line = run.lines[0]
    assert line.quantity == 100
    assert line.needed_quantity == 1


def test_run_allocation_moq_surplus_included_in_free_shipping_threshold(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Порог бесплатной доставки учитывает MOQ-излишек, не исходную
    потребность."""
    session, *_ = db_session
    supplier = make_supplier(
        flat_fee=10.0, free_shipping_threshold=90.0,
    )
    material = make_material()
    # потребность 1 * 1.00 = 1.00 (далеко ниже порога 90), MOQ=100 ->
    # order_total = 100.00 (выше порога 90) -> бесплатная доставка.
    make_price(material, supplier, price=1.00, availability=1000, min_order_qty=100)
    project = make_project([(material, 1)])

    run = run_allocation(session, project.id)

    summary = run.supplier_summaries[0]
    assert summary["free_shipping_achieved"] is True
    assert summary["delivery_fee"] == 0.0
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Run: `cd backend && python -m pytest tests/allocation/test_service.py -v -k "needed_quantity or moq"`
Ожидается: FAIL — `run_allocation` сегодня не передаёт `order_qty` в
`PriceInput` (обязательное поле после Task 1, значит текущий код даже не
скомпилируется на вызове `PriceInput(...)` без `order_qty`) и не пишет
`needed_quantity` на `AllocationLine`.

- [ ] **Шаг 3: Реализация**

```python
# backend/app/allocation/service.py — заменить блок построения materials/price_inputs
# внутри run_allocation (строки, где сегодня строится список materials и price_inputs)

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
    material_ids = {item.material_id for item in project_items}
    demand_by_material_id = {
        str(item.material_id): item.quantity for item in project_items
    }

    prices = db.scalars(
        select(Price).where(Price.material_id.in_(material_ids), Price.valid_to.is_(None))
    ).all()

    # ADR-0045: order_qty = max(потребность материала, Price.min_order_qty
    # или 0), посчитано один раз здесь, по аналогии с _to_cents --
    # обычная Python-константа на входе в солвер, не переменная CP-SAT.
    price_inputs = [
        PriceInput(
            material_id=str(price.material_id),
            supplier_id=str(price.supplier_id),
            unit_price_cents=_to_cents(price.price),
            availability=price.availability,
            order_qty=max(
                demand_by_material_id[str(price.material_id)],
                price.min_order_qty or 0,
            ),
        )
        for price in prices
    ]
```

```python
# backend/app/allocation/service.py — заменить блок записи AllocationLine внутри run_allocation

        for line in result.lines:
            db.add(
                AllocationLine(
                    allocation_run_id=run.id,
                    material_id=uuid.UUID(line.material_id),
                    supplier_id=uuid.UUID(line.supplier_id),
                    quantity=line.quantity,
                    needed_quantity=(
                        line.needed_quantity if line.needed_quantity != line.quantity else None
                    ),
                    unit_price=_from_cents(line.unit_price_cents),
                    line_total=_from_cents(line.line_total_cents),
                )
            )
```

- [ ] **Шаг 4: Убедиться, что тесты проходят**

Run: `cd backend && python -m pytest tests/allocation/test_service.py -v`
Ожидается: PASS на всех тестах файла (включая старые — потребность и
MOQ=1 из фикстуры `make_price` по умолчанию дают `order_qty == quantity`,
поведение не меняется).

- [ ] **Шаг 5: Прогнать полный набор `tests/allocation/` на регрессию**

Run: `cd backend && python -m pytest tests/allocation/ -q`
Ожидается: PASS, число пройденных тестов равно базовой линии (249) плюс
все новые тесты этого плана на данный момент.

- [ ] **Шаг 6: Commit**

```bash
git add backend/app/allocation/service.py backend/tests/allocation/test_service.py
git commit -m "feat(allocation): run_allocation computes order_qty and persists needed_quantity (ADR-0045)"
```

---

### Task 7: API-схемы — `needed_quantity` в `AllocationLineOut`/`OrderItemOut`

**Файлы:**
- Изменить: `backend/app/api/schemas/allocation.py`
- Изменить: `backend/app/api/schemas/order.py`
- Изменить: `backend/app/api/order.py` (`_to_order_item_out`)
- Тест: `backend/tests/allocation/test_api.py`
- Тест: `backend/tests/allocation/test_order.py`

**Интерфейсы:**
- Потребляет: `AllocationLine.needed_quantity`/`OrderItem.needed_quantity` (Task 5)
- Производит: `AllocationLineOut.needed_quantity: int | None`, `OrderItemOut.needed_quantity: int | None`

Контекст: `AllocationLineOut`/`OrderItemOut` используют
`model_config = ConfigDict(from_attributes=True)` — Pydantic читает поле
прямо из ORM-атрибута по имени, значит добавление поля в схему с тем же
именем, что на модели, достаточно само по себе для `AllocationLineOut`. Для
`OrderItemOut` поле собирается вручную в `_to_order_item_out`, поэтому туда
нужна явная правка.

- [ ] **Шаг 1: Написать падающие тесты**

```python
# backend/tests/allocation/test_api.py — добавить в конец файла

def test_allocation_line_out_exposes_needed_quantity_when_moq_creates_surplus(
    client, db_session, make_supplier, make_material, make_price, make_project,
    make_user, make_session, auth_cookie,
):
    """GET .../allocations/{run_id} отдаёт needed_quantity != null, когда у
    выбранного поставщика MOQ выше потребности. Сегодня AllocationLineOut
    не имеет этого поля вообще -- чистое добавление."""
    session, *_ = db_session
    user = make_user(role="employee")
    user_session = make_session(user)
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=1.00, availability=1000, min_order_qty=100)
    project = make_project([(material, 37)])

    response = client.post(
        f"/projects/{project.id}/allocate", cookies=auth_cookie(user_session)
    )
    run_id = response.json()["id"]

    response = client.get(
        f"/projects/{project.id}/allocations/{run_id}", cookies=auth_cookie(user_session)
    )

    line = response.json()["lines"][0]
    assert line["quantity"] == 100
    assert line["needed_quantity"] == 37


def test_allocation_line_out_needed_quantity_null_when_no_moq_surplus(
    client, db_session, make_supplier, make_material, make_price, make_project,
    make_user, make_session, auth_cookie,
):
    session, *_ = db_session
    user = make_user(role="employee")
    user_session = make_session(user)
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=1.00, availability=1000, min_order_qty=1)
    project = make_project([(material, 37)])

    response = client.post(
        f"/projects/{project.id}/allocate", cookies=auth_cookie(user_session)
    )
    run_id = response.json()["id"]

    response = client.get(
        f"/projects/{project.id}/allocations/{run_id}", cookies=auth_cookie(user_session)
    )

    line = response.json()["lines"][0]
    assert line["needed_quantity"] is None
```

Примечание для исполнителя: если `client`/`auth_cookie`/похожие фикстуры
называются иначе в `tests/allocation/test_api.py` — открыть этот файл
первым (`cat backend/tests/allocation/test_api.py | head -80`) и
скопировать точный паттерн аутентификации существующего теста на том же
эндпоинте (`POST /projects/{project_id}/allocate`), а не угадывать имена
фикстур из этого плана.

```python
# backend/tests/allocation/test_order.py — добавить в конец файла

def test_order_item_out_exposes_needed_quantity_from_allocation_line(
    db_session, make_supplier, make_material, make_price, make_project,
):
    """create_orders_for_run переносит AllocationLine.needed_quantity в
    OrderItem.needed_quantity без изменений -- проверяем через прямой вызов
    service-функций (не HTTP), т.к. это внутренний перенос данных, не
    API-контракт сам по себе (тот проверяется в test_api.py выше для
    AllocationLineOut)."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=1.00, availability=1000, min_order_qty=100)
    project = make_project([(material, 37)])

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)

    item = orders[0].items[0]
    assert item.quantity == 100
    assert item.needed_quantity == 37
```

Примечание: проверить точные импорты, которые уже используются в начале
`test_order.py` (`run_allocation`, `create_orders_for_run`) — скопировать их,
не придумывать заново.

- [ ] **Шаг 2: Убедиться, что тесты падают**

Run: `cd backend && python -m pytest tests/allocation/test_api.py -v -k "needed_quantity"`
Run: `cd backend && python -m pytest tests/allocation/test_order.py -v -k "needed_quantity"`
Ожидается: FAIL — `needed_quantity` отсутствует в обеих Pydantic-схемах,
ключ не будет в JSON-ответе / `OrderItem` ещё не получает его при создании
(это будет исправлено в Task 9, здесь пока падает по этой причине —
нормально, Task 9 допишет перенос в `create_orders_for_run`; если к этому
шагу Task 9 ещё не сделана, тест `test_order_item_out_exposes_needed_quantity_from_allocation_line`
временно пропустить флагом `pytest.mark.skip` с явной причиной "ждёт
Task 9" и вернуться к нему после неё — порядок задач в этом плане
допускает такую короткую отложенность одного теста).

- [ ] **Шаг 3: Реализация — добавить поле в схемы**

```python
# backend/app/api/schemas/allocation.py — добавить в класс AllocationLineOut,
# сразу после поля quantity

    needed_quantity: int | None = None
    """Исходная потребность материала, когда MOQ выбранного поставщика
    создал излишек (quantity > needed_quantity). NULL = MOQ не действовал.
    См. AllocationLine.needed_quantity, ADR-0045."""
```

```python
# backend/app/api/schemas/order.py — добавить в класс OrderItemOut,
# сразу после поля quantity

    needed_quantity: int | None = None
    """Перенесено из AllocationLine.needed_quantity при создании Order --
    исходная потребность материала, когда MOQ создал излишек. NULL = MOQ
    не действовал на момент расчёта. См. ADR-0045."""
```

```python
# backend/app/api/order.py — внутри _to_order_item_out, добавить needed_quantity
# в конструктор OrderItemOut, сразу после quantity=item.quantity

    return OrderItemOut(
        id=item.id,
        order_id=item.order_id,
        material_id=item.material_id,
        raw_description=item.raw_description,
        quantity=item.quantity,
        needed_quantity=item.needed_quantity,
        quoted_price=item.quoted_price,
        # ... остальные поля без изменений
    )
```

- [ ] **Шаг 4: Убедиться, что тесты проходят (после Task 9 для order-теста, если он был временно пропущен)**

Run: `cd backend && python -m pytest tests/allocation/test_api.py tests/allocation/test_order.py -v -k "needed_quantity"`
Ожидается: PASS.

- [ ] **Шаг 5: Commit**

```bash
git add backend/app/api/schemas/allocation.py backend/app/api/schemas/order.py backend/app/api/order.py backend/tests/allocation/test_api.py backend/tests/allocation/test_order.py
git commit -m "feat(api): expose needed_quantity on AllocationLineOut/OrderItemOut (ADR-0045)"
```

---

### Task 8: Наследование `min_order_qty` при PDF-реимпорте (`apply.py`)

**Файлы:**
- Изменить: `backend/app/price_ingestion/apply.py`
- Тест: `backend/tests/price_ingestion/test_apply.py` (найти существующий файл теста для `_apply_match`, добавить туда)

**Интерфейсы:**
- Потребляет: ничего нового
- Производит: `_apply_match(db, entry, supplier_id, material_id) -> None` — та же сигнатура, но если `entry.min_order_qty is None`, новая `Price` наследует `min_order_qty` от закрываемой строки (симметрично уже работающей логике `version_price` в `app/api/price.py:67`).

Контекст: сегодня `_apply_match` (apply.py:69-79) безусловно пишет
`min_order_qty=entry.min_order_qty` — если новая выгрузка прайса не
содержит MOQ в строке, активный `Price.min_order_qty` тихо затирается в
`NULL`, даже если он был сохранён ранее. Это существующий дефект,
фиксируемый в рамках ADR-0045 (см. §Решение/Модель данных).

- [ ] **Шаг 1: Найти существующий тестовый файл для `_apply_match`**

Run: `cd backend && grep -rln "_apply_match\|apply_price_list_entry" tests/`

- [ ] **Шаг 2: Написать падающий тест**

```python
# добавить в найденный файл теста (вероятно tests/price_ingestion/test_apply.py)

def test_apply_match_inherits_moq_from_closed_price_when_entry_has_none(
    db_session, make_material, make_supplier, make_price_list_import,
):
    """Реимпорт прайса без указанного MOQ в строке не стирает ранее
    сохранённый Price.min_order_qty активной строки -- симметрично
    version_price() (app/api/price.py:67). Регрессия против дефекта,
    зафиксированного в ADR-0045 §Решение/Модель данных."""
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()

    old_price = Price(
        material_id=material.id, supplier_id=supplier.id,
        price=1.00, currency="USD", availability=None,
        min_order_qty=250,
        valid_from=datetime.date(2026, 1, 1), valid_to=None,
    )
    session.add(old_price)
    session.flush()

    import_ = make_price_list_import(supplier=supplier)
    entry = PriceListEntry(
        import_id=import_.id,
        supplier_raw_name="test raw name",
        price=1.10, currency="USD",
        min_order_qty=None,  # новая выгрузка не упоминает MOQ
    )
    session.add(entry)
    session.flush()

    _apply_match(session, entry, supplier.id, material.id)

    new_price = (
        session.query(Price)
        .filter(Price.material_id == material.id, Price.supplier_id == supplier.id, Price.valid_to.is_(None))
        .one()
    )
    assert new_price.min_order_qty == 250


def test_apply_match_overwrites_moq_when_entry_has_explicit_value(
    db_session, make_material, make_supplier, make_price_list_import,
):
    """Явное новое значение в выгрузке перезаписывает старое -- поведение
    без изменений относительно сегодняшнего, зафиксировано здесь как
    регрессия рядом с тестом наследования выше."""
    session, *_ = db_session
    material = make_material()
    supplier = make_supplier()

    old_price = Price(
        material_id=material.id, supplier_id=supplier.id,
        price=1.00, currency="USD", availability=None,
        min_order_qty=250,
        valid_from=datetime.date(2026, 1, 1), valid_to=None,
    )
    session.add(old_price)
    session.flush()

    import_ = make_price_list_import(supplier=supplier)
    entry = PriceListEntry(
        import_id=import_.id,
        supplier_raw_name="test raw name",
        price=1.10, currency="USD",
        min_order_qty=500,  # новая выгрузка явно указывает другое значение
    )
    session.add(entry)
    session.flush()

    _apply_match(session, entry, supplier.id, material.id)

    new_price = (
        session.query(Price)
        .filter(Price.material_id == material.id, Price.supplier_id == supplier.id, Price.valid_to.is_(None))
        .one()
    )
    assert new_price.min_order_qty == 500
```

Примечание для исполнителя: `make_price_list_import` — проверить точное имя
фикстуры в найденном conftest.py (может называться иначе); если такой
фикстуры нет, создать `PriceListImport` напрямую в теле теста по образцу
соседних тестов того же файла, не изобретать новую фикстуру ради одного
теста.

- [ ] **Шаг 3: Убедиться, что первый тест падает, второй проходит**

Run: `cd backend && python -m pytest tests/price_ingestion/test_apply.py -v -k "inherits_moq or overwrites_moq"`
Ожидается: `test_apply_match_inherits_moq_from_closed_price_when_entry_has_none` — FAIL
(`new_price.min_order_qty` будет `None`, не `250`). Второй тест — PASS уже сейчас
(существующее поведение не меняется для явного значения).

- [ ] **Шаг 4: Реализация**

```python
# backend/app/price_ingestion/apply.py — заменить функцию _apply_match целиком

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

    # ADR-0045: если выгрузка не упоминает MOQ в этой строке, наследуем от
    # закрываемой строки -- симметрично version_price() (app/api/price.py:67),
    # которая уже делает это для всех остальных путей записи Price. Без
    # этого PDF-реимпорт тихо затирал ранее сохранённый MOQ в NULL каждый
    # раз, когда парсер не извлёк его из текущей выгрузки.
    min_order_qty = entry.min_order_qty
    if min_order_qty is None and active_price is not None:
        min_order_qty = active_price.min_order_qty

    new_price = Price(
        material_id=material_id,
        supplier_id=supplier_id,
        price=entry.price,
        currency=entry.currency,
        availability=entry.availability,
        min_order_qty=min_order_qty,
        valid_from=datetime.date.today(),
        valid_to=None,
        source_import_id=entry.import_id,
    )
    db.add(new_price)
    _upsert_alias(db, supplier_id, material_id, entry.supplier_raw_name)

    entry.matched_material_id = material_id
    entry.action = "match"
    db.commit()
```

- [ ] **Шаг 5: Убедиться, что оба теста проходят**

Run: `cd backend && python -m pytest tests/price_ingestion/test_apply.py -v`
Ожидается: PASS на всём файле.

- [ ] **Шаг 6: Commit**

```bash
git add backend/app/price_ingestion/apply.py backend/tests/price_ingestion/test_apply.py
git commit -m "fix(price-ingestion): inherit min_order_qty on PDF reimport when entry omits it (ADR-0045)"
```

---

### Task 9: Override строки аллокации пересчитывает `quantity`/`needed_quantity`/`line_total`

**Файлы:**
- Изменить: `backend/app/allocation/service.py` (`override_allocation_line_supplier`)
- Тест: `backend/tests/allocation/test_override.py`

**Интерфейсы:**
- Потребляет: `AllocationLine.needed_quantity` (Task 5)
- Производит: `override_allocation_line_supplier(db, run_id, line_id, new_supplier_id, ...) -> AllocationLine` — та же сигнатура, но теперь пересчитывает `line.quantity` от `max(needed_quantity или текущий quantity, new_price.min_order_qty или 0)`.

Контекст: сегодня (service.py:348-350) override пересчитывает только
`unit_price`/`line_total`, оставляя `quantity` нетронутым — корректно до
этого ADR (потребность не завязана на выбранного поставщика), но неверно
после него (у нового поставщика может быть свой, другой MOQ).

- [ ] **Шаг 1: Прочитать существующие тесты override, чтобы не продублировать паттерн**

Run: `cd backend && grep -n "def test_override_flags_below_min_order_without_blocking\|def test_override_clears_below_min_order" tests/allocation/test_override.py`

- [ ] **Шаг 2: Написать падающие тесты**

```python
# backend/tests/allocation/test_override.py — добавить в конец файла

def test_override_recomputes_quantity_and_total_for_moq(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Override строки аллокации на поставщика с MOQ выше needed_quantity
    пересчитывает и quantity, и line_total, не только unit_price --
    регрессия против сегодняшнего service.py (override не трогал quantity
    вообще). Потребность 37, исходный поставщик без MOQ (quantity=37,
    needed_quantity=NULL), новый поставщик с MOQ=200."""
    session, *_ = db_session
    cheap_no_moq = make_supplier(name="Cheap", flat_fee=0.0, free_shipping_threshold=0.0)
    high_moq = make_supplier(name="HighMOQ", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, cheap_no_moq, price=1.00, availability=1000, min_order_qty=1)
    make_price(material, high_moq, price=0.50, availability=1000, min_order_qty=200)
    project = make_project([(material, 37)])

    run = run_allocation(session, project.id)
    line = run.lines[0]
    assert line.supplier_id == cheap_no_moq.id  # дешевле при demand=37, без MOQ-излишка
    assert line.quantity == 37
    assert line.needed_quantity is None

    updated = override_allocation_line_supplier(
        session, run.id, line.id, high_moq.id
    )

    assert updated.supplier_id == high_moq.id
    assert updated.quantity == 200  # max(37, MOQ=200)
    assert updated.needed_quantity == 37
    assert float(updated.line_total) == 100.00  # 200 * 0.50


def test_override_clears_moq_adjustment_when_no_longer_applicable(
    db_session, make_supplier, make_material, make_price, make_project
):
    """Override на поставщика без MOQ-проблемы очищает needed_quantity
    обратно в NULL -- из строки, у которой до этого был MOQ-излишек от
    другого поставщика."""
    session, *_ = db_session
    high_moq = make_supplier(name="HighMOQ", flat_fee=0.0, free_shipping_threshold=0.0)
    no_moq = make_supplier(name="NoMOQ", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, high_moq, price=0.50, availability=1000, min_order_qty=200)
    make_price(material, no_moq, price=10.00, availability=1000, min_order_qty=1)
    project = make_project([(material, 37)])

    run = run_allocation(session, project.id)
    line = run.lines[0]
    assert line.supplier_id == high_moq.id  # дешевле по полной стоимости с излишком
    assert line.quantity == 200
    assert line.needed_quantity == 37

    updated = override_allocation_line_supplier(
        session, run.id, line.id, no_moq.id
    )

    assert updated.supplier_id == no_moq.id
    assert updated.quantity == 37  # max(37, MOQ=1) == 37, MOQ больше не действует
    assert updated.needed_quantity is None
    assert float(updated.line_total) == 370.00
```

- [ ] **Шаг 3: Убедиться, что тесты падают**

Run: `cd backend && python -m pytest tests/allocation/test_override.py -v -k "moq"`
Ожидается: FAIL — `updated.quantity` останется равным старому значению
(override сегодня не трогает `quantity`), `needed_quantity` не пересчитывается.

- [ ] **Шаг 4: Реализация**

```python
# backend/app/allocation/service.py — заменить блок внутри override_allocation_line_supplier,
# начиная с "if line.overridden_at is None:" до "db.flush()" (строки ~344-354)

    if line.overridden_at is None:
        line.original_supplier_id = line.supplier_id
        line.original_unit_price = line.unit_price

    # ADR-0045: потребность берётся из needed_quantity, если она уже была
    # зафиксирована предыдущим MOQ-расхождением (строка уже заказывалась с
    # излишком у другого поставщика), иначе из текущего line.quantity (MOQ
    # ещё не действовал, значит line.quantity сам по себе -- потребность).
    demand = line.needed_quantity if line.needed_quantity is not None else line.quantity
    new_quantity = max(demand, new_price.min_order_qty or 0)

    line.supplier_id = new_supplier_id
    line.unit_price = new_price.price
    line.quantity = new_quantity
    line.needed_quantity = demand if new_quantity != demand else None
    line.line_total = float(new_price.price) * new_quantity
    line.overridden_at = datetime.now(timezone.utc)
    line.overridden_via_order_item_id = source_order_item_id
    line.overridden_by_user_id = overridden_by_user_id
    db.flush()
```

- [ ] **Шаг 5: Убедиться, что тесты проходят**

Run: `cd backend && python -m pytest tests/allocation/test_override.py -v`
Ожидается: PASS на всём файле (включая существующие тесты —
`test_override_flags_below_min_order_without_blocking` и аналогичные,
которые не трогают MOQ явно и используют дефолтный `min_order_qty=1` из
фикстуры `make_price`, где `new_quantity == demand` всегда).

- [ ] **Шаг 6: Commit**

```bash
git add backend/app/allocation/service.py backend/tests/allocation/test_override.py
git commit -m "fix(allocation): override recomputes quantity/needed_quantity for new supplier's MOQ (ADR-0045)"
```

---

### Task 10: `find_replacement_candidates` — `availability_risk` от MOQ кандидата, не от строки

**Файлы:**
- Изменить: `backend/app/allocation/order_service.py`
- Тест: `backend/tests/allocation/test_find_replacement.py`

**Интерфейсы:**
- Потребляет: `AllocationLine.needed_quantity`/`quantity` (Task 5, Task 9)
- Производит: `find_replacement_candidates(db, order_id, item_id) -> tuple[uuid.UUID, list[dict]]` — та же сигнатура, но `availability_risk` для каждого кандидата считается от его собственного `candidate_order_qty = max(line.needed_quantity или line.quantity, candidate_price.min_order_qty или 0)`.

Контекст: сегодня (order_service.py:280-290) `availability_risk` сравнивает
`price.availability` каждого кандидата с `line.quantity` **текущего**
(заменяемого) поставщика — после ADR-0045 `line.quantity` может уже
включать MOQ-излишек **текущего** поставщика, который не обязан совпадать
с тем, что было бы заказано у **кандидата** (у кандидата свой MOQ).

- [ ] **Шаг 1: Прочитать текущий тестовый файл**

Run: `cd backend && cat tests/allocation/test_find_replacement.py | head -60`

- [ ] **Шаг 2: Написать падающий тест**

```python
# backend/tests/allocation/test_find_replacement.py — добавить в конец файла

def test_availability_risk_uses_candidate_own_moq_not_line_quantity(
    db_session, make_supplier, make_material, make_price, make_project,
):
    """line.quantity у текущего (заменяемого) поставщика уже включает его
    собственный MOQ-излишек (200, при потребности 37). Кандидат с
    availability=50 должен сравниваться не с line.quantity=200 текущего
    поставщика, а со своим собственным order_qty = max(needed_quantity=37,
    candidate.min_order_qty=1) = 37 -- у кандидата своего MOQ-требования
    выше потребности нет, значит availability=50 >= 37 -> risk=False, хотя
    50 < line.quantity(200) -- регрессия против сегодняшнего
    order_service.py:286-287, которое сравнило бы 50 < 200 и дало бы
    risk=True неверно."""
    session, *_ = db_session
    high_moq_current = make_supplier(name="CurrentHighMOQ", flat_fee=0.0, free_shipping_threshold=0.0)
    low_availability_candidate = make_supplier(name="Candidate", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, high_moq_current, price=0.50, availability=1000, min_order_qty=200)
    make_price(material, low_availability_candidate, price=5.00, availability=50, min_order_qty=1)
    project = make_project([(material, 37)])

    run = run_allocation(session, project.id)
    assert run.lines[0].supplier_id == high_moq_current.id
    assert run.lines[0].quantity == 200
    assert run.lines[0].needed_quantity == 37

    orders = create_orders_for_run(session, project.id, run.id)
    order = orders[0]
    item = order.items[0]

    line_id, candidates = find_replacement_candidates(session, order.id, item.id)

    candidate_entry = next(
        c for c in candidates if c["supplier_id"] == low_availability_candidate.id
    )
    assert candidate_entry["availability_risk"] is False


def test_availability_risk_true_when_candidate_cannot_cover_its_own_moq_demand(
    db_session, make_supplier, make_material, make_price, make_project,
):
    """Кандидат с MOQ выше своей собственной потребности и недостаточным
    availability относительно этого MOQ -- risk=True, посчитанный от его
    собственного order_qty, не от line.quantity текущего поставщика."""
    session, *_ = db_session
    current = make_supplier(name="Current", flat_fee=0.0, free_shipping_threshold=0.0)
    risky_candidate = make_supplier(name="RiskyCandidate", flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, current, price=1.00, availability=1000, min_order_qty=1)
    make_price(material, risky_candidate, price=0.80, availability=50, min_order_qty=100)
    project = make_project([(material, 37)])

    run = run_allocation(session, project.id)
    assert run.lines[0].quantity == 37  # MOQ=1 у текущего, нет излишка

    orders = create_orders_for_run(session, project.id, run.id)
    order = orders[0]
    item = order.items[0]

    line_id, candidates = find_replacement_candidates(session, order.id, item.id)

    candidate_entry = next(
        c for c in candidates if c["supplier_id"] == risky_candidate.id
    )
    # candidate_order_qty = max(37, 100) = 100; availability=50 < 100 -> risk=True
    assert candidate_entry["availability_risk"] is True
```

Примечание для исполнителя: проверить точные импорты
(`create_orders_for_run`, `find_replacement_candidates`, `run_allocation`),
уже используемые в начале файла — скопировать, не придумывать заново.

- [ ] **Шаг 3: Убедиться, что тесты падают**

Run: `cd backend && python -m pytest tests/allocation/test_find_replacement.py -v -k "candidate_own_moq or candidate_cannot_cover"`
Ожидается: FAIL на первом тесте (сегодняшний код даст `risk=True`, сравнив
50 < 200, тест ожидает `False`).

- [ ] **Шаг 4: Реализация**

```python
# backend/app/allocation/order_service.py — заменить блок построения candidates
# внутри find_replacement_candidates (строки ~280-290)

    # ADR-0045: для каждого кандидата считаем его СОБСТВЕННЫЙ order_qty --
    # line.quantity текущего (заменяемого) поставщика мог уже включать его
    # MOQ-излишек, который не обязан совпадать с тем, что заказали бы у
    # кандидата (у кандидата свой, другой MOQ). Потребность берётся из
    # needed_quantity, если она зафиксирована, иначе line.quantity сам по
    # себе является потребностью (MOQ текущего поставщика не действовал).
    demand = line.needed_quantity if line.needed_quantity is not None else line.quantity

    candidates = [
        {
            "supplier_id": price.supplier_id,
            "supplier_name": names_by_id[price.supplier_id],
            "price": float(price.price),
            "availability": price.availability,
            "availability_risk": price.availability is not None
            and price.availability < max(demand, price.min_order_qty or 0),
        }
        for price in prices
    ]
    return line.id, candidates
```

- [ ] **Шаг 5: Убедиться, что тесты проходят**

Run: `cd backend && python -m pytest tests/allocation/test_find_replacement.py -v`
Ожидается: PASS на всём файле.

- [ ] **Шаг 6: Commit**

```bash
git add backend/app/allocation/order_service.py backend/tests/allocation/test_find_replacement.py
git commit -m "fix(allocation): find_replacement availability_risk uses candidate's own MOQ (ADR-0045)"
```

---

### Task 11: `create_orders_for_run` переносит `needed_quantity` в `OrderItem`

**Файлы:**
- Изменить: `backend/app/allocation/order_service.py` (`create_orders_for_run`, `replace_and_sync_order`)
- Тест: `backend/tests/allocation/test_order.py` (тест уже написан в Task 7, Шаг 1 — здесь делаем реализацию, которая его зафиксирует)

**Интерфейсы:**
- Потребляет: `AllocationLine.needed_quantity` (Task 5)
- Производит: `create_orders_for_run(...)`, `replace_and_sync_order(...)` — те же сигнатуры, `OrderItem(...)` конструкторы внутри получают `needed_quantity=line.needed_quantity`.

Эта задача делает то, что Task 7 предполагала (и возможно временно
пропустила тестом) — перенос поля при создании `OrderItem`. Если Task 7
была выполнена раньше и тест `test_order_item_out_exposes_needed_quantity_from_allocation_line`
был помечен `skip`, сейчас самое время его реализовать и снять пропуск.

- [ ] **Шаг 1: Если тест из Task 7 помечен `@pytest.mark.skip` — снять пометку**

Открыть `backend/tests/allocation/test_order.py`, найти
`test_order_item_out_exposes_needed_quantity_from_allocation_line`, убрать
декоратор `@pytest.mark.skip(...)`, если он был добавлен.

- [ ] **Шаг 2: Убедиться, что тест падает (если ещё не проверяли)**

Run: `cd backend && python -m pytest tests/allocation/test_order.py::test_order_item_out_exposes_needed_quantity_from_allocation_line -v`
Ожидается: FAIL — `item.needed_quantity` будет `AttributeError` или `None`
по умолчанию модели, тест ожидает `37`.

- [ ] **Шаг 3: Реализация — два construction sites `OrderItem(...)`**

```python
# backend/app/allocation/order_service.py — внутри create_orders_for_run,
# блок "for line in lines:" (строки ~658-666)

        for line in lines:
            db.add(
                OrderItem(
                    order_id=order.id,
                    material_id=line.material_id,
                    quantity=line.quantity,
                    needed_quantity=line.needed_quantity,
                    quoted_price=line.unit_price,
                )
            )
            line.ordered_at = now
```

```python
# backend/app/allocation/order_service.py — внутри replace_and_sync_order,
# блок db.add(OrderItem(...)) (строки ~452-459)

    db.add(
        OrderItem(
            order_id=target_order.id,
            material_id=line.material_id,
            quantity=line.quantity,
            needed_quantity=line.needed_quantity,
            quoted_price=candidate["price"],
        )
    )
```

- [ ] **Шаг 4: Убедиться, что тест проходит**

Run: `cd backend && python -m pytest tests/allocation/test_order.py -v`
Run: `cd backend && python -m pytest tests/allocation/test_replace_and_order.py -v`
Ожидается: PASS на обоих файлах.

- [ ] **Шаг 5: Написать и прогнать дополнительный тест на `needed_quantity is None` (перенос без искажения)**

```python
# backend/tests/allocation/test_order.py — добавить в конец файла

def test_create_orders_copies_null_needed_quantity_when_no_moq_surplus(
    db_session, make_supplier, make_material, make_price, make_project,
):
    """Перенос needed_quantity=None (нет MOQ-расхождения) в OrderItem
    остаётся None, не становится 0 и не становится line.quantity."""
    session, *_ = db_session
    supplier = make_supplier(flat_fee=0.0, free_shipping_threshold=0.0)
    material = make_material()
    make_price(material, supplier, price=1.00, availability=1000, min_order_qty=1)
    project = make_project([(material, 37)])

    run = run_allocation(session, project.id)
    orders = create_orders_for_run(session, project.id, run.id)

    item = orders[0].items[0]
    assert item.quantity == 37
    assert item.needed_quantity is None
```

Run: `cd backend && python -m pytest tests/allocation/test_order.py -v -k "null_needed_quantity"`
Ожидается: PASS.

- [ ] **Шаг 6: Прогнать полный набор `tests/allocation/`**

Run: `cd backend && python -m pytest tests/allocation/ -q`
Ожидается: PASS, число пройденных тестов — базовая линия (249) плюс все
новые тесты этого плана.

- [ ] **Шаг 7: Commit**

```bash
git add backend/app/allocation/order_service.py backend/tests/allocation/test_order.py
git commit -m "feat(allocation): create_orders_for_run copies needed_quantity to OrderItem (ADR-0045)"
```

---

### Task 12: `current_active_min_order_qty` в `PriceListEntryOut` (симметрично ADR-0040)

**Файлы:**
- Изменить: `backend/app/api/schemas/price_ingestion.py`
- Изменить: файл, где строится `PriceListEntryOut` (найти через grep — вероятно рядом с `current_active_price`)
- Тест: файл теста, где уже покрыт `current_active_price` (найти через grep)

**Интерфейсы:**
- Производит: `PriceListEntryOut.current_active_min_order_qty: int | None = None`

Контекст: нужно для фронтенд-предупреждения на экране ревью PDF-импорта
(Task 14) — "MOQ не был указан в этом прайсе, но у активной цены стоит N".
`current_active_price` (ADR-0040) уже решает ту же задачу для цены — делаем
по тому же паттерну для MOQ.

- [ ] **Шаг 1: Найти, где вычисляется `current_active_price` для `PriceListEntryOut`**

Run: `cd backend && grep -rn "current_active_price" app/ | grep -v schemas`

- [ ] **Шаг 2: Прочитать найденный код, чтобы понять точный паттерн вычисления**

Прочитать функцию/блок, где `current_active_price` заполняется (вероятно
через join/lookup `Price` по `(supplier_id, matched_material_id)` с
`valid_to IS NULL`). Скопировать ту же структуру для `min_order_qty`, не
придумывать новый запрос.

- [ ] **Шаг 3: Написать падающий тест**

Исполнитель: найти существующий тест на `current_active_price` в
`PriceListEntryOut` (`grep -rln "current_active_price" tests/`), прочитать
его целиком, и добавить рядом тест с тем же сетапом, но проверяющий
`current_active_min_order_qty`:

```python
# добавить в найденный тестовый файл, используя тот же сетап/фикстуры,
# что соседний тест на current_active_price

def test_price_list_entry_out_exposes_current_active_min_order_qty(
    # те же фикстуры, что соседний тест current_active_price
):
    """Симметрично ADR-0040's current_active_price -- PriceListEntryOut
    отдаёт min_order_qty активной Price той же пары (supplier, matched_material),
    даже если текущая строка импорта не упоминает MOQ вообще."""
    # Сетап: активная Price с min_order_qty=250 для (supplier, material);
    # PriceListEntry с min_order_qty=None, matched_material_id=material.id.
    # Assert: response/schema.current_active_min_order_qty == 250.
    ...
```

- [ ] **Шаг 4: Убедиться, что тест падает**

Run: `cd backend && python -m pytest <найденный_файл_теста> -v -k "current_active_min_order_qty"`
Ожидается: FAIL — поле не существует в схеме.

- [ ] **Шаг 5: Реализация**

```python
# backend/app/api/schemas/price_ingestion.py — добавить в класс PriceListEntryOut,
# сразу после current_active_price

    current_active_min_order_qty: int | None = None
    """Active Price.min_order_qty (valid_to IS NULL) for this supplier +
    matched_material_id, at read time -- симметрично current_active_price
    (ADR-0040). NULL по тем же причинам: matched_material_id NULL, или нет
    активной Price для пары, или активная Price сама имеет min_order_qty=NULL.
    См. ADR-0045."""
```

Добавить вычисление `current_active_min_order_qty` рядом с вычислением
`current_active_price` в найденном на Шаге 1 коде — тот же lookup `Price`,
просто дополнительно читаем `.min_order_qty` с той же найденной строки
(не отдельный запрос, если `current_active_price` уже получает всю строку
`Price`, а не только `.price`).

- [ ] **Шаг 6: Убедиться, что тест проходит**

Run: `cd backend && python -m pytest <найденный_файл_теста> -v`
Ожидается: PASS на всём файле.

- [ ] **Шаг 7: Commit**

```bash
git add backend/app/api/schemas/price_ingestion.py <изменённый_файл_с_вычислением> <тестовый_файл>
git commit -m "feat(price-ingestion): expose current_active_min_order_qty on PriceListEntryOut (ADR-0045)"
```

---

### Task 13: Frontend — предупреждения на `AllocationResultPage`/`OrderDetailPage`, регрессия `buildOrderText`

**Файлы:**
- Изменить: `frontend/src/routes/AllocationResultPage.tsx`
- Изменить: `frontend/src/routes/OrderDetailPage.tsx`
- Тест: `frontend/src/routes/AllocationResultPage.test.tsx`
- Тест: `frontend/src/routes/OrderDetailPage.test.tsx`

**Интерфейсы:**
- Потребляет: `AllocationLineOut.needed_quantity`/`OrderItemOut.needed_quantity` (Task 7)

Это самая важная задача плана с точки зрения правила "никогда не доходит
до поставщика" (Review Focus п.5) — у неё есть регрессионный тест,
закрывающий именно этот риск.

- [ ] **Шаг 1: Прочитать текущую структуру `buildOrderText`/`buildTargetPriceOrderText`**

Run: `cd frontend && grep -n "buildOrderText\|buildTargetPriceOrderText" src/routes/OrderDetailPage.tsx`

- [ ] **Шаг 2: Написать падающий регрессионный тест на `buildOrderText`**

```typescript
// frontend/src/routes/OrderDetailPage.test.tsx — добавить в конец файла,
// используя существующий паттерн построения тестового OrderItemOut из
// соседних тестов этого же файла (скопировать структуру объекта, не
// придумывать поля заново)

describe("buildOrderText never includes needed_quantity (ADR-0045)", () => {
  it("does not render needed_quantity anywhere in the output text", () => {
    const item = {
      // ...скопировать базовую структуру OrderItemOut из соседнего теста,
      // переопределив:
      quantity: 100,
      needed_quantity: 37,
    };

    const text = buildOrderText(/* существующие аргументы функции */);

    expect(text).not.toContain("37");
    expect(text).toContain("100");
  });
});
```

Исполнитель: прочитать реальную сигнатуру `buildOrderText` и
`buildTargetPriceOrderText` (строки 667-714/731+ по ADR) перед написанием
теста — скопировать точные параметры вызова из существующего теста на эти
функции в этом же файле, а не угадывать их здесь.

- [ ] **Шаг 3: Убедиться, что тест проходит сразу (это тест на ОТСУТСТВИЕ изменения — проверка, что поле не просочилось туда само)**

Run: `cd frontend && npm run test -- OrderDetailPage.test.tsx -t "buildOrderText never includes needed_quantity"`
Ожидается: PASS сразу — `buildOrderText` ещё не знает про `needed_quantity`
вообще, значит он физически не может его вывести. Это ожидаемо: тест
фиксирует текущее (корректное) поведение как регрессионный барьер на
будущее, не обнаруживает баг сейчас.

- [ ] **Шаг 4: Написать падающие тесты на сами предупреждения**

```typescript
// frontend/src/routes/AllocationResultPage.test.tsx — добавить в конец файла

describe("MOQ surplus warning (ADR-0045)", () => {
  it("shows a warning when needed_quantity is set on a line", () => {
    // Рендер страницы с AllocationLineOut, где quantity=100, needed_quantity=37.
    // Скопировать паттерн рендера/мока API-ответа из существующего теста
    // этого файла (например того, что рендерит below_min_order).
    render(/* ... */);

    expect(screen.getByText(/100.*37|37.*100/i)).toBeInTheDocument();
  });

  it("shows no warning when needed_quantity is null", () => {
    render(/* line с needed_quantity: null */);

    expect(screen.queryByText(/из-за минимального количества заказа/i)).not.toBeInTheDocument();
  });
});
```

```typescript
// frontend/src/routes/OrderDetailPage.test.tsx — добавить в конец файла

describe("MOQ surplus warning on OrderItem (ADR-0045)", () => {
  it("shows a warning when needed_quantity is set on an item", () => {
    // Рендер с OrderItemOut, где quantity=100, needed_quantity=37.
    render(/* ... */);

    expect(screen.getByText(/100.*37|37.*100/i)).toBeInTheDocument();
  });
});
```

- [ ] **Шаг 5: Убедиться, что тесты падают**

Run: `cd frontend && npm run test -- AllocationResultPage.test.tsx OrderDetailPage.test.tsx -t "MOQ surplus warning"`
Ожидается: FAIL — предупреждения ещё не реализованы.

- [ ] **Шаг 6: Реализация на `AllocationResultPage.tsx`**

Исполнитель: открыть файл, найти, где рендерится строка `AllocationLine`
(вероятно таблица/карточка на уровне материала), и добавить условный блок:

```tsx
{line.needed_quantity != null && (
  <div className="moq-surplus-warning">
    Заказано {line.quantity} вместо {line.needed_quantity} из-за минимального
    количества заказа у поставщика.
  </div>
)}
```

Использовать существующий визуальный компонент предупреждения, если он уже
есть в файле (например `AvailabilityWarning`-подобный паттерн из
`PriceComparisonPage.tsx`) — скопировать его стиль/класс, не изобретать
новый визуальный язык для предупреждений на этой странице.

- [ ] **Шаг 7: Реализация на `OrderDetailPage.tsx`**

Аналогично, в месте рендера строки `OrderItem`:

```tsx
{item.needed_quantity != null && (
  <div className="moq-surplus-warning">
    Заказано {item.quantity} вместо {item.needed_quantity} из-за минимального
    количества заказа у поставщика.
  </div>
)}
```

**Важно**: этот блок добавляется ТОЛЬКО в рендер страницы (видимый
пользователю текст интерфейса), НЕ в `buildOrderText`/
`buildTargetPriceOrderText` — те функции продолжают читать только
`item.quantity`/`item.quoted_price`/`material.unit`, без изменений.

- [ ] **Шаг 8: Убедиться, что все тесты проходят**

Run: `cd frontend && npm run test -- AllocationResultPage.test.tsx OrderDetailPage.test.tsx`
Ожидается: PASS на обоих файлах, включая регрессионный тест на
`buildOrderText` из Шага 2 — он должен оставаться PASS и после правок
Шагов 6-7 (это и есть сама проверка: добавление UI-предупреждения не
затронуло текст ордера).

- [ ] **Шаг 9: Ручная проверка в браузере (golden path и edge case)**

Запустить dev-сервер, открыть страницу расчёта аллокации для тестового
проекта с материалом, у которого есть поставщик с MOQ выше потребности —
убедиться, что предупреждение отображается корректно визуально (не только
в тесте), и что страница без MOQ-расхождения выглядит как раньше (edge
case "MOQ не задан" не должен менять вид экрана). Задокументировать
результат в сообщении коммита или в PR-описании.

- [ ] **Шаг 10: Commit**

```bash
git add frontend/src/routes/AllocationResultPage.tsx frontend/src/routes/OrderDetailPage.tsx frontend/src/routes/AllocationResultPage.test.tsx frontend/src/routes/OrderDetailPage.test.tsx
git commit -m "feat(frontend): show MOQ surplus warning on allocation/order pages, never in order text (ADR-0045)"
```

---

### Task 14: Frontend — предупреждения на `PriceComparisonPage`/`PriceListImportReviewPage`

**Файлы:**
- Изменить: `frontend/src/routes/.../PriceComparisonPage.tsx` (точный путь — найти через поиск)
- Изменить: `frontend/src/routes/.../PriceListImportReviewPage.tsx` (точный путь — найти через поиск)
- Тест: соответствующие `.test.tsx` файлы

**Интерфейсы:**
- Потребляет: `current_active_min_order_qty` (Task 12)

- [ ] **Шаг 1: Найти точные пути файлов**

Run: `cd frontend && find src -iname "PriceComparisonPage.tsx" -o -iname "PriceListImportReviewPage.tsx"`

- [ ] **Шаг 2: Прочитать существующий паттерн `AvailabilityWarning` в `PriceComparisonPage.tsx`**

Run: `grep -n "AvailabilityWarning" <найденный_путь>/PriceComparisonPage.tsx`

Прочитать его реализацию целиком (строки 239-246/337-347 по ADR) — новое
предупреждение должно визуально следовать тому же паттерну, не вводить
отдельный стиль.

- [ ] **Шаг 3: Написать падающий тест на `PriceComparisonPage`**

```typescript
// <путь>/PriceComparisonPage.test.tsx — добавить в конец файла

describe("MOQ warning for candidate with MOQ above required quantity (ADR-0045)", () => {
  it("shows surplus cost warning when required_quantity < candidate min_order_qty", () => {
    // Рендер с кандидатом, у которого required_quantity=37, min_order_qty=100,
    // price=0.50 -- используя структуру пропсов, скопированную из
    // соседнего теста на AvailabilityWarning этого же файла.
    render(/* ... */);

    expect(screen.getByText(/100.*37|37.*100/i)).toBeInTheDocument();
    // итоговая стоимость на order_qty (100 * 0.50 = 50.00), не на потребности
    expect(screen.getByText(/50/)).toBeInTheDocument();
  });
});
```

- [ ] **Шаг 4: Написать падающий тест на `PriceListImportReviewPage`**

```typescript
// <путь>/PriceListImportReviewPage.test.tsx — добавить в конец файла

describe("MOQ warning when entry omits MOQ but active price has one (ADR-0045)", () => {
  it("shows warning when entry.min_order_qty is null and current_active_min_order_qty is set", () => {
    // Рендер строки ревью с entry.min_order_qty=null,
    // entry.current_active_min_order_qty=250.
    render(/* ... */);

    expect(screen.getByText(/250/)).toBeInTheDocument();
  });

  it("shows no warning when both are null or entry has its own value", () => {
    render(/* entry.min_order_qty=null, current_active_min_order_qty=null */);

    expect(screen.queryByText(/MOQ.*не.*был.*указан/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Шаг 5: Убедиться, что тесты падают**

Run: `cd frontend && npm run test -- PriceComparisonPage.test.tsx PriceListImportReviewPage.test.tsx -t "MOQ"`
Ожидается: FAIL — предупреждения не реализованы.

- [ ] **Шаг 6: Реализация на `PriceComparisonPage.tsx`**

Добавить рядом с кандидатом-поставщиком блок (по образцу
`AvailabilityWarning`):

```tsx
{candidate.required_quantity < candidate.min_order_qty && (
  <div className="moq-warning">
    Выбор этого поставщика означает закупку {Math.max(candidate.required_quantity, candidate.min_order_qty)}{" "}
    вместо {candidate.required_quantity}, итоговая стоимость:{" "}
    {formatMoney(Math.max(candidate.required_quantity, candidate.min_order_qty) * candidate.price)}
  </div>
)}
```

Контекст: все денежные операции должны быть уже посчитаны backend'ом по
CLAUDE.md принципу 4 — если `required_quantity`/`min_order_qty`/`price`
уже приходят с backend в составе кандидата, умножение на фронте для
ОТОБРАЖЕНИЯ (не для записи в БД) допустимо по тому же принципу, что
`price_delta`/`price_delta_pct` в `OrderItemOut` сегодня вычисляются на
чтении (backend), но если фронт уже умножает `price * quantity` где-то
рядом в этом же файле для других целей (проверить существующий код перед
реализацией) — использовать тот же паттерн, не вводить новую логику
умножения денег на фронте, если backend может отдать готовое число.
**Исполнитель должен сначала проверить, не стоит ли эту сумму посчитать и
отдать backend'ом (в `ReplacementCandidateOut`/аналогичной схеме) вместо
умножения на фронте** — если в `order_service.py`/схемах кандидатов уже
есть похожий паттерн для других денежных величин, следовать ему.

- [ ] **Шаг 7: Реализация на `PriceListImportReviewPage.tsx`**

```tsx
{entry.min_order_qty == null && entry.current_active_min_order_qty != null && (
  <div className="moq-warning">
    MOQ не был указан в этом прайсе, но у активной цены стоит{" "}
    {entry.current_active_min_order_qty}
  </div>
)}
```

- [ ] **Шаг 8: Убедиться, что тесты проходят**

Run: `cd frontend && npm run test -- PriceComparisonPage.test.tsx PriceListImportReviewPage.test.tsx`
Ожидается: PASS на обоих файлах.

- [ ] **Шаг 9: Ручная проверка в браузере**

Открыть экран сравнения цен для материала с кандидатом, у которого MOQ
выше требуемого количества — убедиться, что предупреждение и
пересчитанная стоимость отображаются корректно. Открыть экран ревью
PDF-импорта для строки без MOQ у материала, который уже имеет активный
MOQ — убедиться в отображении предупреждения. Задокументировать результат.

- [ ] **Шаг 10: Commit**

```bash
git add <путь>/PriceComparisonPage.tsx <путь>/PriceListImportReviewPage.tsx <путь>/PriceComparisonPage.test.tsx <путь>/PriceListImportReviewPage.test.tsx
git commit -m "feat(frontend): show MOQ warnings on price comparison and import review pages (ADR-0045)"
```

---

### Task 15: Документация — `docs/data-model.md`, `docs/architecture.md`, `docs/spec.md`

**Файлы:**
- Изменить: `docs/data-model.md`
- Изменить: `docs/architecture.md` (если менялась структура потоков)
- Изменить: `docs/spec.md`

Не код — финальная задача плана, закрывающая требование CLAUDE.md "после
завершения значимого куска работы обновить docs/, не оставлять на потом".

- [ ] **Шаг 1: Обновить `docs/data-model.md`**

Добавить описание:
- Семантика `Price.min_order_qty`: минимальное количество заказа на связке
  (материал, поставщик), используется в расчёте аллокации с ADR-0045.
  Единица измерения принимается равной единице измерения
  `Price`/`ProjectItem.quantity` для той же пары — допущение, не
  проверяемое кодом (см. ADR-0045 §Последствия).
- Новые колонки `AllocationLine.needed_quantity`/`OrderItem.needed_quantity`:
  nullable, `NULL` = MOQ не создал расхождения с потребностью; заполнено =
  исходная потребность, когда `quantity` выше неё из-за MOQ.

- [ ] **Шаг 2: Обновить `docs/architecture.md`, если менялась структура потоков через солвер**

Если в этом файле есть диаграмма потока "project_items → price_inputs →
solver → AllocationLine" — добавить упоминание, что `price_inputs` теперь
несёт `order_qty`, посчитанный в `service.py`, до вызова солвера.

- [ ] **Шаг 3: Обновить `docs/spec.md:168`**

Отметить "минимальная сумма заказа / кратность упаковки" как частично
закрытый вопрос: MOQ (минимум) закрыт ADR-0045, кратность упаковки
(покупка только шагом N) остаётся открытым вопросом, не решённым этим ADR.

- [ ] **Шаг 4: Commit**

```bash
git add docs/data-model.md docs/architecture.md docs/spec.md
git commit -m "docs: document MOQ semantics and needed_quantity fields (ADR-0045)"
```

---

## Финальная проверка перед завершением ветки

- [ ] Полный backend-прогон: `cd backend && pytest -q` — сравнить итоговое
  число passed с базовой линией до начала этого плана (249 в
  `tests/allocation/`, плюс полный набор остальных директорий) — любое
  новое падение, не упомянутое в известных issues (`test_bootstrap_admin`),
  исследовать до коммита.
- [ ] `cd backend && ruff check .`
- [ ] `cd frontend && npm run lint && npm run test && npm run build`
- [ ] Напоминание (не выполнять в рамках этого плана): деплой на прод
  заблокирован до решения пользователя по фактическим значениям MOQ
  (ADR-0045 §План выкатки п.3) — финальный коммит этого плана оставляет
  код на dev, готовым к деплою, но НЕ деплоит его.
