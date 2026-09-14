# ADR-0033: Лёгкая позиция ордера без материала из каталога (`OrderItem.material_id` nullable)

Статус: Предложено

## Контекст

`ParseResponseSection` (`OrderDetailPage.tsx`, ADR-0018 §3) раскладывает
распознанный ответ поставщика на три категории: "Совпало" (строка
сопоставлена с уже существующим `OrderItem`), "Отсутствует в ответе"
(наш `OrderItem`, не встретившийся в документе) и "Лишнее" —
`matched_order_item_id: null`, поставщик прислал позицию, которой не
было в нашем плане/ордере вообще.

ADR-0018 §5 явно решил, что кнопка "Добавить" на строке категории
"Лишнее" создаёт `PurchaseRecord` (ADR-0008), не `OrderItem` —
обоснование там было прямым следствием инварианта ADR-0007 п.1/п.2:
`Order`/`OrderItem` — снимок того, что мы **уже отправили** поставщику
(`quoted_price NOT NULL` ровно потому, что "Order не может существовать
без цены, по которой его создали", ADR-0007 §1), значит физически не
может быть строки `OrderItem` для позиции, которую мы никогда не
заказывали — для неё нет числа, которое мы бы посчитали и отправили.

**На практике этот путь не решает задачу, ради которой существует.**
Подтверждено пользователем на реальном сценарии: сотрудник распознаёт
ответ поставщика, видит в "Лишнем" позицию, которую **решает добавить в
заказ** (например, поставщик предложил замену или сопутствующий товар,
и сотрудник хочет её заказать), нажимает "Добавить" — и ничего не
появляется ни в таблице `Order` на экране, ни в копируемом тексте
(`buildOrderText`/`buildTargetPriceOrderText`, ADR-0027 §5), который
уходит следующим сообщением поставщику. `PurchaseRecord` фиксирует то,
что уже куплено (ADR-0008 п.1: "факт покупки, не план") — здесь же речь
о позиции, которую только предстоит заказать, на следующей итерации
торга того же `Order`. Разные сущности для разных моментов процесса, и
ADR-0018 §5 отправил в разные хранилища то, что на самом деле относится
к одному и тому же ещё не отправленному заказу.

**Почему инвариант ADR-0007 п.1/п.2 здесь не блокирует.** Тот инвариант
защищал `quoted_price` — числа, которое физически не существует для
позиции, никогда не заказывавшейся. В этой задаче `quoted_price` для
такой строки **есть** — это цена, которую поставщик сам назвал в
документе (`ParsedExtraLine.price`, ADR-0018 §2). Отсутствует не цена, а
`material_id`: строка описывает нечто, чего нет в нашем каталоге
`Material` под известным `internal_sku`. Это другой пробел, чем тот,
который рассматривал и отклонял ADR-0018 §5 (там обсуждалась nullable
`quoted_price`, а не nullable `material_id`) — снимок остаётся снимком
("что мы получили в ответ и хотим заказать"), просто без канонической
привязки к каталогу.

Матчинг `raw_description` в конкретный `material_id` каталога (по
аналогии с ИИ-matching прайс-листов, `docs/spec.md` §3, или ручным
выбором через `MaterialCombobox`) явно вынесен пользователем за рамки
этой задачи — не откладывается молча, фиксируется здесь как условие
возврата (см. "Не в объёме").

## Решение

### 1. Модель данных — `material_id` nullable + `raw_description`

```python
class OrderItem(UUIDPKMixin, Base):
    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    material_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("materials.id"))
    raw_description: Mapped[str | None] = mapped_column(String(500))
    quantity: Mapped[int] = mapped_column(nullable=False)
    quoted_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    ...  # confirmed_price/received_price/target_price/declined_at/decline_reason не меняются
```

`quantity`/`quoted_price` остаются `NOT NULL` без изменений — инвариант
ADR-0007 п.1 про "Order не может существовать без цены" сохраняется
буквально, просто цена/количество теперь могут описывать позицию без
`material_id`, а не только с ним.

**Инвариант — ровно одно из `material_id`/`raw_description` всегда
заполнено, никогда оба и никогда ни одного.** Обеспечивается
CHECK-constraint на уровне БД, не только кодом (то же рассуждение, по
которому ADR-0031 п.1 хранит `color_fragment` явной колонкой, а не
доверяет коду пересчитывать инвариант при каждом обращении):

```sql
ALTER TABLE order_items
  ALTER COLUMN material_id DROP NOT NULL,
  ADD COLUMN raw_description VARCHAR(500);

ALTER TABLE order_items
  ADD CONSTRAINT ck_order_items_material_xor_raw_description
  CHECK ((material_id IS NOT NULL) != (raw_description IS NOT NULL));
```

Существующие строки (`material_id` всегда заполнен, `raw_description`
всегда `NULL`) удовлетворяют constraint автоматически — миграция не
требует backfill ни одной существующей записи.

**Отклонено: `raw_description` без CHECK-constraint, полагаться на код
приложения.** Тот же класс риска, что уже explicitly отвергнут для
`color_options`/`color_fragment` в ADR-0031 — новый путь в коде (прямой
`INSERT`, будущий скрипт-миграция данных) мог бы молча создать строку с
обоими полями или ни одним, и ничего в схеме БД этого бы не поймало.
Constraint — дешёвая гарантия на уровне, откуда её нельзя обойти.

### 2. Создание лёгкой строки — новый узкий эндпоинт, только для draft

```
POST /orders/{order_id}/items/raw
{ "raw_description": "...", "quantity": 2, "quoted_price": 18.95 }
```

- `order.status != "draft"` → `409` — та же гвардия, что уже
  подразумевают остальные мутации состава ордера (создание `OrderItem`
  через `create_orders_for_run` происходит один раз при генерации,
  дальнейшие изменения состава — только пока ордер черновик).
- Создаёт `OrderItem(order_id=order_id, material_id=None,
  raw_description=payload.raw_description, quantity=payload.quantity,
  quoted_price=payload.quoted_price)`. `confirmed_price`/
  `received_price`/`target_price`/`declined_at`/`decline_reason` —
  `NULL` при создании, редактируются тем же существующим
  `PATCH /orders/{order_id}/items/{item_id}` (`set_order_item_fields`,
  ADR-0013 §3), без изменений в его сигнатуре — этот ADR не трогает тот
  контракт, лёгкая строка проходит через него наравне с обычной для
  всех операций, которые для неё применимы (п.3).
- Эндпоинт не принимает `material_id` в теле вообще — невозможно через
  этот путь случайно создать строку, одновременно привязанную к
  каталогу и несущую `raw_description`.
- Возвращает `OrderItemOut` (`material_id: null`, `raw_description`
  заполнен, остальные поля как у любого нового `OrderItem`).

**Фронтенд.** `ExtraLineRow` (`OrderDetailPage.tsx`) — кнопка
"Добавить" вызывает `ordersApi.addRawItem(order.id, {raw_description,
quantity, unit_price})` вместо `purchaseRecordsApi.create(...)`. После
успеха — существующий колбэк `onApplied()` (полный `GET`, тот же
паттерн, что "Применить все совпадения", ADR-0018 §4), кнопка меняется
на "Добавлено ✓" как сейчас (ADR-0018 §3c) — видимое поведение кнопки
не меняется, меняется только то, куда она пишет.

**`PurchaseRecord`-путь ADR-0018 §5 полностью выводится из
употребления для этой кнопки, не остаётся альтернативным вариантом.**
Одна кнопка — один смысл. Фактическая закупка по-прежнему фиксируется
отдельно, вручную, на экране "Фактическая закупка" (ADR-0008 §5) —
после того, как ордер реально отправлен/оплачен, не в момент разбора
ответа поставщика. Эта задача не меняет ADR-0008 ни в чём.

### 3. Лёгкая строка — усечённый функционал, явно не участвует в price-comparison/override/find-replacement

По требованию задачи: лёгкая строка — не полноценная позиция каталога,
участвует только в том, что не требует резолва в `Material`
(количество/цена, `confirm`/`decline`/`target_price`, отображение в
таблице и копируемом тексте). Полная карта мест, где
`OrderItem.material_id` сейчас предполагается всегда заполненным
(собрана сканированием кодовой базы), и решение для каждого:

**Backend — явно блокируется, `422`, не крэш:**
- `find_replacement_candidates` (`order_service.py`) — в начале функции
  `if item.material_id is None: raise HTTPException(422, "Материал не
  из каталога — подбор замены недоступен")`.
- `replace_and_sync_order` (override поставщика на строке,
  `order_service.py`) — тот же guard в начале функции. Сейчас оба места
  делают `db.get(Material, item.material_id)` и сразу читают
  `.canonical_name` — при `material_id=None` это `AttributeError` на
  `None`, не осмысленная ошибка; explicit-проверка заменяет крэш понятным
  4xx.
- Фронтенд: `ReplacementTrigger` (`OrderDetailPage.tsx`) не рендерится
  (или рендерится задизейбленной с подсказкой) для строки с
  `item.material_id == null` — тот же принцип "UI-зеркало серверной
  защиты, не единственная защита", что уже применён к `hasColorChoiceMaterial`
  (ADR-0031 §3): backend — источник истины по доступности действия, но
  недоступная в интерфейсе кнопка не заставляет сотрудника узнавать об
  этом через ошибку сервера.

**Backend — молча пропускается, не ошибка, просто "не применимо":**
- `_detect_price_divergence` (`order_service.py`) — `if item.material_id
  is None: return None` в начале. Нет активной `Price` на
  несуществующий материал, значит нет расхождения по определению; PATCH
  `confirmed_price` на лёгкой строке проходит нормально (сотрудник может
  подтвердить/скорректировать цену), просто без секции
  `price_divergence` в ответе — фронтенд (`PriceDivergenceModal`,
  батч-подтверждение ADR-0030 §4) не трогается вообще: раз backend
  никогда не производит `price_divergence` для такой строки, эти
  компоненты просто никогда не получают её на вход.
- `price_comparison.py` (проектный экран сравнения цен между
  поставщиками) — уже естественно исключает такие строки без
  дополнительного кода: сравнение идёт от `ProjectItem.material_id`,
  `None == material_id` никогда не совпадает.

**Backend — fallback на `raw_description` вместо крэша:**
- `app/order_response_parser/service.py::_order_items_context` —
  сейчас безусловно строит промпт-контекст через
  `item.material.canonical_name` для каждой строки `order.items`;
  меняется на `item.material.canonical_name if item.material_id else
  item.raw_description`. Реальный риск без фикса: одно повторное
  распознавание ответа на *том же* ордере после добавления лёгкой
  строки упадёт `AttributeError`, потому что промпт-контекст строится по
  всем текущим `OrderItem`.
- `app/api/order.py::parse_order_response_endpoint` — построение
  `MissingItemOut` для категории "Отсутствует в ответе" (ADR-0018 §3b)
  делает то же безусловное обращение к `item.material.canonical_name`,
  та же замена.
- `OrderItemOut.material_id` (`app/api/schemas/order.py`) →
  `uuid.UUID | None`; новое поле `OrderItemOut.raw_description:
  str | None`. `_to_order_item_out` (`app/api/order.py`) передаёт
  `raw_description=item.raw_description` наравне с остальными полями.

**Frontend — fallback на `raw_description`:**
- `buildOrderText`/`buildTargetPriceOrderText` (`OrderDetailPage.tsx`,
  ADR-0027 §5/§7г) — текущий fallback `material ? resolveMaterialName(...)
  : item.material_id` (сырой UUID-строкой, только чтобы не упасть на
  `undefined`) меняется на `material ? resolveMaterialName(...) :
  (item.raw_description ?? item.material_id)`. Это прямая причина, ради
  которой затевалась вся задача — сотрудник должен увидеть осмысленный
  текст, а не UUID, в сообщении, которое уходит поставщику.
- Главная таблица ордера (строка материала в `OrderItemRow`) — тот же
  fallback, тот же принцип, что уже применяет `MatchedLineRow` (ADR-0018
  §3a) с его собственной цепочкой `material?.canonical_name ??
  orderItem?.material_id ?? line.raw_description` — не новый паттерн в
  кодовой базе, применение уже существующего к ещё одному месту.

### 4. Не в объёме

- **Матчинг `raw_description` в `material_id` каталога** (ИИ или ручной
  выбор через `MaterialCombobox`) — явно отложено пользователем в этой
  задаче. Условие возврата: если появится запрос "превратить лёгкую
  строку в полноценную позицию каталога задним числом" — отдельная
  небольшая задача (один PATCH-путь, проставляющий `material_id` и
  очищающий `raw_description`, тот же CHECK-constraint уже гарантирует
  корректность перехода), не архитектурное изменение, вероятно не
  требует нового ADR, если не меняет ничего из решённого здесь.
- **Участие лёгкой строки в price-comparison/override/find-replacement**
  — осознанно исключено (§3), не "TODO на потом" в рамках этой задачи.
- **`PurchaseRecordsPage`/остальной путь фактической закупки** — не
  меняется нигде, кроме самой кнопки "Добавить" на экране `OrderDetailPage`.

## Альтернативы

**JSON-поле `Order.extra_lines` вместо nullable `OrderItem.material_id`.**
Рассмотрено, отклонено. Завело бы второй параллельный источник данных
для состава ордера — `buildOrderText` пришлось бы читать из двух мест
(`order.items` и `order.extra_lines`), а любая будущая фича, работающая
с составом ордера (price-comparison, override, экспорт), заново решала
бы, учитывать ли второй источник. Тот самый класс риска, который уже
explicitly избегает ADR-0031 п.4 ("одна функция вместо трёх копий
парсинга") — здесь тот же принцип на уровне модели данных, не функции:
`OrderItem` остаётся единственным источником истины для состава ордера,
вместо того чтобы завести параллельный.

**Оставить обе кнопки — "Добавить в фактическую закупку" (текущая,
`PurchaseRecord`) и "Добавить в ордер" (новая) — рядом на строке.**
Рассмотрено, отклонено пользователем явно: один клик должен означать
одно решение. Держать оба пути одновременно на одной строке создаёт
двусмысленность ровно там, где сотрудник принимает решение быстро,
разбирая ответ поставщика — то, ADR-0018 §4 уже explicitly избегал
("массовое применение это не «автоматически без проверки», это
«проверено и подтверждено одним действием»" — двусмысленный выбор между
двумя похожими кнопками — источник ошибок того же рода, которого это
рассуждение избегает).

**Nullable `material_id` без `raw_description`, показывать пустую
строку/UUID для лёгкой позиции.** Рассмотрено, отклонено — сделало бы
задачу технически решённой (constraint не нарушен), но не решённой по
существу: сотрудник не увидел бы, что именно за материал добавлен, ни в
таблице, ни в тексте для поставщика. `raw_description` — не
опциональное удобство, а единственный источник смысла для строки без
`material_id`.

## Последствия

- Новая Alembic-миграция: `order_items.material_id` теряет `NOT NULL`,
  новая колонка `order_items.raw_description VARCHAR(500)`, новый
  CHECK-constraint `ck_order_items_material_xor_raw_description`. Не
  требует backfill — все существующие строки уже удовлетворяют
  constraint.
- Новый endpoint `POST /orders/{order_id}/items/raw`
  (`backend/app/api/order.py`), доступен только для `order.status ==
  "draft"` (`409` иначе).
- `OrderItemOut.material_id` → `Optional[uuid.UUID]`, новое поле
  `OrderItemOut.raw_description: str | None`
  (`backend/app/api/schemas/order.py`).
- Guard-проверки в `find_replacement_candidates`, `replace_and_sync_order`
  (`422` при `material_id is None`) и `_detect_price_divergence`
  (молчаливый no-op) — все три в `backend/app/allocation/order_service.py`.
- Fallback на `raw_description` в
  `backend/app/order_response_parser/service.py::_order_items_context`
  и в построении `MissingItemOut`
  (`backend/app/api/order.py::parse_order_response_endpoint`) — оба пути
  сейчас безусловно крэшнутся на лёгкой строке без этой правки.
- Frontend: `ExtraLineRow` (`OrderDetailPage.tsx`) переключается на
  новый эндпоинт вместо `purchaseRecordsApi.create`;
  `buildOrderText`/`buildTargetPriceOrderText`/главная таблица ордера
  получают fallback на `raw_description`; `ReplacementTrigger` не
  рендерится (или дизейблится) для лёгкой строки.
- `docs/decisions/0018-ai-order-response-parsing.md` §5 — отмечается как
  пересмотренный этим ADR в части "куда пишет кнопка «Добавить» в
  категории «Лишнее»"; остальные решения ADR-0018 (модель распознавания,
  три категории, массовое применение, отсутствие персистентного
  хранения файла) не затронуты и остаются в силе как есть.
- `docs/ui-reference.md` — раздел "Блок «Лишнее»" переписывается:
  вместо `PurchaseRecordCreate` описывает `POST
  /orders/{order_id}/items/raw` и поведение "Добавлено ✓" в терминах
  `OrderItem`.
- `docs/data-model.md` — `OrderItem.material_id` отмечается nullable,
  добавляется `OrderItem.raw_description`, документируется
  взаимоисключающий constraint.
- Тесты (backend, обязательны): `POST .../items/raw` на draft-ордере →
  `201`, `material_id=null`/`raw_description` заполнен; на не-draft
  ордере → `409`; `find_replacement_candidates`/`replace_and_sync_order`
  на лёгкой строке → `422`, не крэш; `PATCH confirmed_price` на лёгкой
  строке → `200`, без `price_divergence` в ответе; повторный
  `parse-response` на ордере, уже содержащем лёгкую строку, не падает;
  CHECK-constraint отклоняет прямую попытку завести строку с обоими или
  ни одним из полей (integration-тест на уровне БД, не только через API).
  Тесты (frontend): `ExtraLineRow` вызывает новый эндпоинт API-клиента,
  не `purchaseRecordsApi.create`; `buildOrderText` показывает
  `raw_description` для лёгкой строки, не сырой `material_id`;
  `ReplacementTrigger` не рендерится для строки без `material_id`.
- Реализация (backend: миграция, эндпоинт, guard'ы, fallback'ы;
  frontend: `ExtraLineRow`, `buildOrderText`/таблица,
  `ReplacementTrigger`) — предмет отдельной задачи через
  `writing-plans`, в объём этого ADR не входит написание кода.
