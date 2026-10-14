"""Проверка одной конкретной alembic-ревизии (needed_quantity на
AllocationLine/OrderItem, ADR-0045) через прямой вызов модульных функций
upgrade()/downgrade() на отдельном соединении, откатываемом в finally --
тот же паттерн, что test_order_item_migration.py (ADR-0033/0034), после
инцидента ADR-0034 с живым alembic против общей dev-БД (см.
docs/known-issues.md, "ИНЦИДЕНТ"). НИКОГДА не вызывает
alembic.command.upgrade/downgrade напрямую против общей БД, и никогда не
коммитит DDL этого теста на реальную схему.

Эта ревизия уже применена к dev-БД (alembic upgrade head в рамках этой же
задачи) -- оба теста сначала downgrade()'ят на своём отдельном соединении
(которое видит текущую реальную схему, включая колонку), чтобы честно
проверить полный цикл upgrade/downgrade внутри одной транзакции,
откатываемой в finally и никогда не коммитящейся на реальную схему.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.database import engine

REVISION_FILE = "50786ee4d5ed_add_needed_quantity_to_allocation_line_.py"


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


def test_upgrade_adds_nullable_columns():
    module = _load_migration_module()
    connection = engine.connect()
    transaction = connection.begin()
    try:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            # Ревизия уже применена к реальной схеме -- откатываем сначала
            # на этом отдельном соединении/транзакции, чтобы честно
            # проверить сам upgrade(), а не его отсутствие.
            module.downgrade()
            module.upgrade()

        inspector = sa.inspect(connection)
        allocation_line_cols = {c["name"] for c in inspector.get_columns("allocation_lines")}
        order_item_cols = {c["name"] for c in inspector.get_columns("order_items")}
        assert "needed_quantity" in allocation_line_cols
        assert "needed_quantity" in order_item_cols
    finally:
        transaction.rollback()
        connection.close()


def test_downgrade_removes_columns():
    module = _load_migration_module()
    connection = engine.connect()
    transaction = connection.begin()
    try:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.downgrade()

        inspector = sa.inspect(connection)
        allocation_line_cols = {c["name"] for c in inspector.get_columns("allocation_lines")}
        order_item_cols = {c["name"] for c in inspector.get_columns("order_items")}
        assert "needed_quantity" not in allocation_line_cols
        assert "needed_quantity" not in order_item_cols
    finally:
        transaction.rollback()
        connection.close()
