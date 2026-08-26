# Архитектура

Актуализируй эту диаграмму при каждом значимом структурном изменении — это основной
"граф знаний" проекта, читаемый и человеком, и Claude Code в начале сессии.

```mermaid
flowchart LR
    subgraph Auth["0. Аутентификация"]
        GoogleOIDC[Google Workspace OIDC] --> AuthRoutes["/auth/login, /auth/callback"]
        AuthRoutes --> SessionDB[(User / UserSession)]
    end

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

    SessionDB -.->|get_current_user / require_role| Ingestion
    SessionDB -.->|get_current_user / require_role| Project
    SessionDB -.->|get_current_user / require_role| Allocation
    SessionDB -.->|get_current_user / require_role| OrderGen
```

## Границы модулей

- **Auth** — Google Workspace OIDC (authorization code + PKCE), сессии в БД
  (`UserSession`), не JWT — см. `docs/decisions/0024-authentication-authorization.md`.
  Единственный источник identity/роли для всех остальных модулей.
- **Ingestion** — единственное место, где решения принимает LLM без гарантии
  правильности; поэтому всегда с человеческим ревью перед записью в `Price`.
- **Allocation** — детерминированный сервис, без вызовов LLM. См. ADR по алгоритму.
- **Order generation** — чистая шаблонизация, без бизнес-логики.

Все 9 бизнес-роутеров (`supplier`/`material`/`price`/`price_ingestion`/
`project`/`allocation`/`order`/`purchase_record` + `/users`) защищены на
уровне `APIRouter(dependencies=[...])` — `require_role("admin")` для
справочных данных (`supplier`/`material`/`price`/`price_ingestion`/`users`),
`get_current_user` (любая роль) для операционной работы
(`project`/`allocation`/`order`/`purchase_record`) — см. ADR-0024 §4/§5.
`health.py` остаётся публичным; `auth.py` смешанный (публичные `/login`,
`/callback`, защищённые `/me`, `/logout`).

## Связанные документы

- Данные: `docs/data-model.md`
- Решения: `docs/decisions/`
- Термины: `docs/glossary.md`
