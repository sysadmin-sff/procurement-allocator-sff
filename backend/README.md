# backend

FastAPI + SQLAlchemy + Alembic + PostgreSQL.

## Установка

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Запуск

```
copy .env.example .env
uvicorn app.main:app --reload
```

## Команды

```
pytest
ruff check .
alembic upgrade head
```

## Тесты

pytest работает только на отдельной БД: `TEST_DATABASE_URL` обязателен, имя БД
должно оканчиваться на `_test` (ADR-0052). В начале прогона БД удаляется и
создаётся заново через `alembic upgrade head`.

```
docker run --rm -d --name sff-test-db -e POSTGRES_PASSWORD=probe -e POSTGRES_DB=procurement_allocator_test -p 127.0.0.1:55432:5432 pgvector/pgvector:pg17
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:probe@127.0.0.1:55432/procurement_allocator_test"
pytest
```

## Деплой

`docs/DEPLOYMENT.md` — обязательные требования к продовому окружению.
Коротко: rate limiting на `/auth/*` (ADR-0024 §10) доверяет
`X-Forwarded-For` только от пира, равного `TRUSTED_PROXY_IP`, а прокси
обязан **заменять** этот заголовок (`proxy_set_header X-Forwarded-For
$remote_addr;`, не `proxy_add_x_forwarded_for`). Без верного
`TRUSTED_PROXY_IP` лимит считает весь офис за одного клиента.
