# ADR-0001: Таблица PriceListImport

Статус: Принято

## Контекст

`docs/data-model.md` (ER-диаграмма) не содержал таблицу `PriceListImport`, но
`docs/spec.md` §2–3 явно описывает её: одна загрузка PDF-прайса поставщика со
своим `file_ref`, `status` (`pending_review`/`approved`/`rejected`),
`uploaded_at`, `parsed_by_ai_at`. `PriceListEntry.import_id` и
`Price.source_import_id` ссылаются на неё — без таблицы это были бы внешние
ключи в никуда.

## Решение

Добавить таблицу `PriceListImport` в модель данных и миграции, как описано в
spec.md §2. `PriceListEntry` получает FK `import_id → PriceListImport.id`,
`Price` получает nullable FK `source_import_id → PriceListImport.id`.

## Альтернативы

Убрать `import_id`/`source_import_id` из `PriceListEntry`/`Price` и оставить
схему строго по ER-диаграмме — отклонено: тогда теряется прослеживаемость
"из какой загрузки PDF взялась эта цена", что нужно для UI ревью (diff
"было/стало" по конкретному прайсу) и для отладки матчинга.

## Последствия

`docs/data-model.md` обновлён — добавлена таблица `PriceListImport` и связи
с ней. Модуль Ingestion (см. `docs/architecture.md`) теперь явно оперирует
сущностью "загрузка прайса", а не только отдельными строками.
