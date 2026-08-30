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

## Деплой

`docs/DEPLOYMENT.md` — обязательные требования к продовому окружению.
Коротко: rate limiting на `/auth/*` (ADR-0024 §10) доверяет
`X-Forwarded-For` только от пира, равного `TRUSTED_PROXY_IP`, а прокси
обязан **заменять** этот заголовок (`proxy_set_header X-Forwarded-For
$remote_addr;`, не `proxy_add_x_forwarded_for`). Без верного
`TRUSTED_PROXY_IP` лимит считает весь офис за одного клиента.
