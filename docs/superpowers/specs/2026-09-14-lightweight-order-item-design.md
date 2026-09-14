# Дизайн: строка ордера без материала из каталога ("лишнее" → черновик)

Дата: 2026-09-14. Статус: одобрено пользователем, готово к ADR + плану реализации.

## Проблема

`ParseResponseSection` (`OrderDetailPage.tsx`) при распознавании ответа
поставщика раскладывает строки на три категории: "Совпало" (есть
`OrderItem`), "Отсутствует в ответе" (есть `OrderItem`, не встретился в
ответе), "Лишнее" (`matched_order_item_id: null` — поставщик прислал
позицию, которой не было в нашем плане/ордере вообще).

Кнопка "Добавить" на строке из "Лишнее" сейчас (ADR-0018 §4,
`docs/ui-reference.md`) создаёт `PurchaseRecord` — запись фактической
закупки, никак не связанную с черновиком `Order`. Это осознанное решение
ADR-0018, но оно не соответствует реальному сценарию использования:
сотрудник хочет увидеть добавленную позицию в самом ордере — и в таблице
на экране, и в копируемом тексте (`buildOrderText`/
`buildTargetPriceOrderText`), — чтобы отправить её поставщику на
следующей итерации торга. `PurchaseRecord`-путь фиксирует то, что уже
куплено; здесь речь о позиции, которая только предлагается к заказу.

Прямое решение — создавать `OrderItem` вместо `PurchaseRecord` — упирается
в то, что `OrderItem.material_id` обязателен (`NOT NULL`, FK на
`materials`), а `raw_description` из ответа поставщика — свободный текст
без резолва в каталог. Матчинг текста в `material_id` (аналог
price-ingestion matching, ADR-0019/0020) явно вынесен за рамки этой
задачи пользователем — нужна лёгкая строка "как распознано", без
привязки к каталогу.

## Решение

### 1. Модель данных — `OrderItem.material_id` nullable + `raw_description`

```
OrderItem
  material_id: UUID | None        -- было NOT NULL, становится nullable
  raw_description: str | None     -- новая колонка
```

Инвариант — **ровно одно из двух всегда заполнено**, никогда оба и
никогда ни одного: обычная строка (`material_id` есть, `raw_description`
пуст) или лёгкая строка (наоборот). Обеспечивается CHECK-constraint на
уровне БД, не только на уровне кода:

```sql
CHECK ((material_id IS NOT NULL) != (raw_description IS NOT NULL))
```

Одна Alembic-ревизия: `ALTER COLUMN material_id DROP NOT NULL`,
`ADD COLUMN raw_description VARCHAR(500)`, `ADD CONSTRAINT ck_order_items_material_xor_raw_description CHECK (...)`.

Существующие строки (`material_id` всегда заполнен) constraint
удовлетворяют автоматически — не требует backfill.

### 2. Создание лёгкой строки — новый узкий эндпоинт

```
POST /orders/{order_id}/items/raw
{ "raw_description": "...", "quantity": 2, "quoted_price": 18.95 }
```

- Только для `order.status == "draft"` — та же гвардия, что уже
  подразумевают остальные мутации ордера (переопределение, decline).
  `order.status != "draft"` → `409`.
- Создаёт `OrderItem(order_id=order_id, material_id=None,
  raw_description=payload.raw_description, quantity=payload.quantity,
  quoted_price=payload.quoted_price)`. Остальные поля (`confirmed_price`,
  `received_price`, `target_price`, `declined_at`, `decline_reason`) —
  `NULL`, доступны для редактирования тем же путём, что у обычных строк
  (`PATCH .../items/{item_id}` не меняется, работает независимо от
  `material_id`).
- Возвращает `OrderItemOut` (материал `null`, `raw_description`
  заполнен).
- Нет отдельного "material_id validation" — эндпоинт не принимает
  `material_id` вообще, поэтому невозможно создать лёгкую строку
  случайно привязанной к каталогу через этот путь.

Фронтенд: `ExtraLineRow` (`OrderDetailPage.tsx`) — кнопка "Добавить"
вызывает `ordersApi.addRawItem(order.id, {raw_description, quantity,
unit_price})` вместо `purchaseRecordsApi.create(...)`. После успеха —
`onApplied()` (существующий колбэк, обновляет `order.items` полным
`GET`, тот же паттерн, что "Применить все совпадения"), кнопка меняется
на "Добавлено ✓" как сейчас. `PurchaseRecord`-путь из ADR-0018 §4 для
этой кнопки полностью выводится из употребления — не остаётся
альтернативным вариантом, не два разных смысла на одной кнопке.

### 3. Защита существующей логики — лёгкая строка не участвует в price-comparison/override/find-replacement

По explicit-требованию: лёгкая строка — усечённый функционал (текст +
цена + количество + confirm/decline/target_price), не полноценная
позиция каталога. Карта всех мест, где `OrderItem.material_id` сейчас
предполагается всегда заполненным (собрана сканированием кодовой базы),
и что делает каждое при `material_id IS NULL`:

**Backend — явно блокируется (4xx, не крэш):**
- `find_replacement_candidates` (`order_service.py`) — на входе
  `if item.material_id is None: raise HTTPException(422, "Материал не
  из каталога — подбор замены недоступен")`. Симметрично: фронтенд не
  рендерит кнопку "Найти замену" (`ReplacementTrigger`) для строки без
  `material_id`, чтобы 422 не был единственной защитой.
- `replace_and_sync_order` (override поставщика на строке) — тот же
  guard в начале функции.

**Backend — молча пропускается (не ошибка, просто "не применимо"):**
- `_detect_price_divergence` — `if item.material_id is None: return
  None` (нет активной `Price` на несуществующий материал, значит нет
  расхождения; PATCH `confirmed_price` на лёгкой строке проходит
  нормально, просто без раздела "price_divergence" в ответе).
- `price_comparison.py` (проектный экран сравнения цен) — уже
  естественно исключает такие строки: сравнение идёт от
  `ProjectItem.material_id`, `None == material_id` никогда не совпадает
  — без дополнительного кода.

**Backend — fallback на `raw_description` вместо крэша:**
- `order_response_parser/service.py::_order_items_context` —
  `item.material.canonical_name if item.material_id else
  item.raw_description` (сейчас безусловно дёргает `.material
  .canonical_name`, упадёт `AttributeError` на `None`).
- `app/api/order.py::parse_order_response_endpoint`'s построение
  `MissingItemOut` — та же замена.
- `OrderItemOut.material_id` → `uuid.UUID | None`, `_to_order_item_out`
  передаёт `raw_description=item.raw_description` в ответ.

**Frontend — fallback на `raw_description`:**
- `buildOrderText`/`buildTargetPriceOrderText` (`OrderDetailPage.tsx`) —
  текущий fallback `material ? resolveMaterialName(...) :
  item.material_id` (сырой UUID-строкой, только чтобы не упасть) меняется
  на `material ? resolveMaterialName(...) : (item.raw_description ??
  item.material_id)`.
- Главная таблица ордера (строка материала в `OrderItemRow`) — тот же
  fallback.
- `ReplacementTrigger` — не рендерится (или дизейблится с подсказкой),
  если `item.material_id == null`.
- `PriceDivergenceModal`/батч-подтверждение расхождений — код не
  трогается: backend по построению никогда не отдаёт
  `price_divergence` для лёгкой строки после серверного guard'а
  (п. "молча пропускается" выше), так что эти компоненты просто никогда
  не получают такую строку на вход.

### 4. Что НЕ входит в объём

- Матчинг `raw_description` → `material_id` каталога (ИИ или ручной
  выбор через `MaterialCombobox`) — явно отложено пользователем,
  условие возврата: если понадобится "превратить" лёгкую строку в
  полноценную позицию каталога задним числом.
- Участие лёгкой строки в price-comparison/override/find-replacement —
  осознанно исключено, не "TODO на потом" в рамках этой задачи.
- Изменение старого пути "Лишнее" → `PurchaseRecord` в
  `PurchaseRecordsPage`/остальном приложении — он не трогается нигде,
  кроме самой этой кнопки на `OrderDetailPage`.

## Альтернативы

**JSON-поле `Order.extra_lines` вместо nullable `OrderItem.material_id`.**
Рассмотрено и отклонено — завело бы второй параллельный источник данных
для текста ордера (`buildOrderText` пришлось бы читать из двух мест),
тот самый класс риска рассинхрона, которого уже explicitly избегает
ADR-0031 (единая функция `resolve_material_name` вместо трёх копий
парсинга). `OrderItem` остаётся единственным источником истины для
состава ордера.

**Держать обе кнопки — "Добавить в фактическую закупку" и "Добавить в
ордер" — рядом.** Рассмотрено, отклонено пользователем явно: одна
кнопка меняет смысл, `PurchaseRecord`-путь для "Лишнего" выходит из
употребления полностью, фактическая закупка фиксируется отдельно после
того, как ордер отправлен/оплачен — не в момент разбора ответа.

## Последствия

- Новая Alembic-миграция: `order_items.material_id` nullable,
  `order_items.raw_description` (новая колонка), CHECK-constraint на их
  взаимоисключение.
- Новый эндпоинт `POST /orders/{order_id}/items/raw`
  (`backend/app/api/order.py`), только для `draft`-ордеров.
- `OrderItemOut.material_id` → `Optional`, новое поле
  `OrderItemOut.raw_description`.
- Guard'ы в `find_replacement_candidates`, `replace_and_sync_order`,
  `_detect_price_divergence` (`backend/app/allocation/order_service.py`).
- Fallback на `raw_description` в `order_response_parser/service.py`,
  `parse_order_response_endpoint`'s `MissingItemOut`.
- Frontend: `ExtraLineRow` переключается на новый эндпоинт;
  `buildOrderText`/`buildTargetPriceOrderText`/главная таблица получают
  fallback на `raw_description`; `ReplacementTrigger` не рендерится для
  лёгкой строки.
- `docs/ui-reference.md` — раздел "Блок «Лишнее»" переписывается:
  вместо `PurchaseRecordCreate` описывает новый эндпоинт и поведение
  "Добавлено ✓" в терминах `OrderItem`.
- ADR-0018 (`docs/decisions/0018-ai-order-response-parsing.md`)
  получает отметку о пересмотре этого конкретного пункта (§4, кнопка
  "Добавить" в "Лишнем"), со ссылкой на новый ADR этой задачи — не
  переписывается задним числом, фиксируется как явное изменение решения.
- Тесты (backend, обязательны): создание лёгкой строки → `200`,
  `material_id=null`/`raw_description` заполнен; `find-replacement`/
  override на лёгкой строке → `422`, не крэш; PATCH `confirmed_price` на
  лёгкой строке → `200`, без `price_divergence`; parse-response с лёгкой
  строкой в `order.items` не падает; CHECK-constraint отклоняет попытку
  завести строку с обоими или ни одним из полей (миграционный/
  integration-тест). Тесты (frontend): `ExtraLineRow` вызывает новый
  эндпоинт, не `purchaseRecordsApi.create`; `buildOrderText` показывает
  `raw_description` для лёгкой строки; `ReplacementTrigger` не
  рендерится для неё.
