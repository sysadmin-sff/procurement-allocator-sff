# Архитектура

Актуализируй эту диаграмму при каждом значимом структурном изменении — это основной
"граф знаний" проекта, читаемый и человеком, и Claude Code в начале сессии.

```mermaid
flowchart LR
    subgraph Ingestion["1. Обновление цен"]
        PDF[PDF прайс-лист] --> Parser[AI-парсер: таблицы/vision]
        Parser --> Matcher[AI-матчинг: embeddings + LLM decision]
        Matcher --> Review[UI ревью diff]
        Review -->|approve| PriceDB[(Price / PriceListEntry)]
    end

    subgraph Project["2. Проект"]
        UI_Project[UI: материалы + кол-во] --> ProjectDB[(Project / ProjectItem)]
    end

    subgraph Allocation["3. Подбор поставщика"]
        ProjectDB --> Engine[ILP solver: OR-Tools]
        PriceDB --> Engine
        Engine --> AllocDB[(AllocationRun / AllocationLine)]
        AllocDB --> ReviewAlloc[UI ревью распределения]
    end

    subgraph OrderGen["4. Ордер"]
        ReviewAlloc -->|approve| OrderDB[(Order / OrderItem)]
        OrderDB --> Doc[Генерация PDF по поставщику]
    end
```

## Границы модулей

- **Ingestion** — единственное место, где решения принимает LLM без гарантии
  правильности; поэтому всегда с человеческим ревью перед записью в `Price`.
- **Allocation** — детерминированный сервис, без вызовов LLM. См. ADR по алгоритму.
- **Order generation** — чистая шаблонизация, без бизнес-логики.

## Связанные документы

- Данные: `docs/data-model.md`
- Решения: `docs/decisions/`
- Термины: `docs/glossary.md`
