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
