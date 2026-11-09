"""Schema of the measurements module (ADR-0051 §3, criterion 5 as amended 2026-11-10).

Runs only on the disposable test database: the root conftest points
DATABASE_URL at it, and `_alembic` re-checks that before every command.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.database import engine
from app.models import Base
from tests.db_guard import require_test_database_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
PREVIOUS_HEAD = "ea480577269c"

MODULE_TABLES = {
    "measurements_leads",
    "measurements_visits",
    "measurements_amo_events",
    "measurements_field_values",
    "measurements_result_attributions",
    "measurements_sync_state",
    "measurements_user_access",
    "measurements_amo_users",
    "measurements_pipeline_statuses",
}

MODULE_INDEXES = {
    "ix_measurements_visits_lead_id_scheduled_at",
    "ix_measurements_visits_task_type_id",
    "ix_measurements_amo_events_lead_id_occurred_at_event_id",
    "ix_measurements_amo_events_entity",
    "ix_measurements_amo_events_event_type_occurred_at",
    "ix_measurements_result_attributions_lead_id",
    "ix_measurements_result_attributions_task_id",
}

# ADR-0051 "Изменение 2026-11-10"; the list lives in docs/known-issues.md.
KNOWN_DRIFT = {
    ("modify_nullable", "allocation_runs.created_at"),
    ("modify_nullable", "categories.created_at"),
    ("remove_constraint", "ck_order_items_material_xor_raw_description"),
    ("remove_constraint", "ck_prices_valid_to_after_valid_from"),
    ("remove_index", "ix_price_list_entries_import_id"),
    ("remove_index", "ix_prices_material_supplier_valid_to"),
    ("remove_index", "ux_prices_active_material_supplier"),
    ("remove_index", "ix_project_templates_name"),
    ("add_constraint", "project_templates(name)"),
    ("remove_index", "ix_supplier_material_aliases_supplier_material"),
    ("remove_index", "ix_user_sessions_user_id"),
    ("remove_index", "ix_users_email"),
    ("remove_index", "ix_users_google_sub"),
}

INSERT_USER = (
    "insert into users (id, email, role, is_active) values (:id, :email, 'employee', true)"
)
VISIT_COLUMNS = (
    "task_id, lead_id, task_type_id, kind, responsible_amo_user_id, scheduled_at, "
    "is_all_day, is_completed, amo_updated_at, amo_created_at, synced_at"
)
VISIT_VALUES = "1, 2, 2, {kind}, 3, now(), false, false, now(), now(), now()"


def _alembic(*args: str) -> subprocess.CompletedProcess:
    require_test_database_url(os.environ["DATABASE_URL"])
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    return result


def _table_names() -> set[str]:
    return set(inspect(engine).get_table_names())


def _drift_key(diff) -> tuple[str, str, str]:
    """Reduces an autogenerate diff to (operation, table, object name)."""
    if isinstance(diff, list):
        operation, _schema, table, column = diff[0][:4]
        return operation, table, f"{table}.{column}"
    operation, target = diff[0], diff[1]
    if operation in {"add_table", "remove_table"}:
        return operation, target.name, target.name
    if operation in {"add_column", "remove_column"}:
        return operation, diff[2], f"{diff[2]}.{diff[3].name}"
    table = target.table.name
    if target.name:
        return operation, table, target.name
    columns = ",".join(column.name for column in target.columns)
    return operation, table, f"{table}({columns})"


@pytest.fixture
def drift() -> list[tuple[str, str, str]]:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return [_drift_key(diff) for diff in compare_metadata(context, Base.metadata)]


def test_migration_is_the_single_child_of_the_previous_head():
    scripts = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))
    children = [
        script.revision
        for script in scripts.walk_revisions()
        if script.down_revision == PREVIOUS_HEAD
    ]
    assert len(children) == 1
    assert scripts.get_heads() == children


def test_upgrade_creates_every_module_table():
    assert MODULE_TABLES <= _table_names()


def test_upgrade_creates_the_sync_and_attribution_indexes():
    inspector = inspect(engine)
    found = {index["name"] for table in MODULE_TABLES for index in inspector.get_indexes(table)}
    assert MODULE_INDEXES <= found


def test_upgrade_downgrade_upgrade_round_trip_leaves_users_untouched():
    user_id = uuid.uuid4()
    email = f"{user_id}@screen-factory-florida.com"
    with engine.begin() as connection:
        connection.execute(
            text(INSERT_USER),
            {"id": user_id, "email": email},
        )
    try:
        _alembic("downgrade", PREVIOUS_HEAD)
        assert not {name for name in _table_names() if name.startswith("measurements_")}
        with engine.connect() as connection:
            assert (
                connection.execute(text("select version_num from alembic_version")).scalar()
                == PREVIOUS_HEAD
            )
            assert (
                connection.execute(
                    text("select role from users where id = :id"), {"id": user_id}
                ).scalar()
                == "employee"
            )
        _alembic("upgrade", "head")
        assert MODULE_TABLES <= _table_names()
    finally:
        _alembic("upgrade", "head")
        with engine.begin() as connection:
            connection.execute(text("delete from users where id = :id"), {"id": user_id})


def test_mapping_after_upgrade_matches_the_adr_table():
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "select enum_id, label, visit_occurred, outcome_type, is_active "
                "from measurements_field_values order by enum_id"
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        (627963, "Closed, Not Sold On-Site", True, "not_sold", True),
        (627965, "Visit Completed (передан в продажу)", True, "completed", True),
        (627967, "Sold On-Site", True, "sold", True),
        (627969, "Declined Before Visit", False, "declined", True),
    ]


def test_module_tables_have_no_drift(drift):
    assert [item for item in drift if item[1].startswith("measurements_")] == []


def test_foreign_drift_is_exactly_the_recorded_list(drift):
    foreign = {
        (operation, name)
        for operation, table, name in drift
        if not table.startswith("measurements_")
    }
    assert foreign == KNOWN_DRIFT


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param(
            f"insert into measurements_visits ({VISIT_COLUMNS}) "
            f"values ({VISIT_VALUES.format(kind=repr('bogus'))})",
            id="visits.kind",
        ),
        pytest.param(
            f"insert into measurements_visits ({VISIT_COLUMNS}, deleted_reason) "
            f"values ({VISIT_VALUES.format(kind=repr('primary'))}, 'bogus')",
            id="visits.deleted_reason",
        ),
        pytest.param(
            "insert into measurements_field_values (enum_id, label, outcome_type) "
            "values (1, 'x', 'bogus')",
            id="field_values.outcome_type",
        ),
        pytest.param(
            "insert into measurements_result_attributions "
            "(id, lead_id, rule, rule_version, computed_at) "
            "values (gen_random_uuid(), 1, 'bogus', 1, now())",
            id="attributions.rule",
        ),
        pytest.param(
            "insert into measurements_result_attributions "
            "(id, lead_id, rule, deadline_source, rule_version, computed_at) "
            "values (gen_random_uuid(), 1, 'cleared', 'bogus', 1, now())",
            id="attributions.deadline_source",
        ),
        pytest.param(
            "insert into measurements_sync_state (stream, last_status) values ('s', 'bogus')",
            id="sync_state.last_status",
        ),
    ],
)
def test_check_constraints_reject_unknown_enum_values(statement):
    with engine.connect() as connection:
        with pytest.raises(IntegrityError, match="ck_measurements_"):
            connection.execute(text(statement))
        connection.rollback()


def test_visit_requires_amo_created_at():
    columns = VISIT_COLUMNS.replace("amo_created_at, ", "")
    values = "1, 2, 2, 'primary', 3, now(), false, false, now(), now()"
    with engine.connect() as connection:
        with pytest.raises(IntegrityError, match="amo_created_at"):
            connection.execute(
                text(f"insert into measurements_visits ({columns}) values ({values})")
            )
        connection.rollback()


def test_deleting_a_user_cascades_to_their_grant():
    user_id = uuid.uuid4()
    with engine.connect() as connection:
        connection.execute(
            text(INSERT_USER),
            {"id": user_id, "email": f"{user_id}@screen-factory-florida.com"},
        )
        connection.execute(
            text("insert into measurements_user_access (user_id, granted_at) values (:id, now())"),
            {"id": user_id},
        )
        connection.execute(text("delete from users where id = :id"), {"id": user_id})
        remaining = connection.execute(
            text("select count(*) from measurements_user_access where user_id = :id"),
            {"id": user_id},
        ).scalar()
        connection.rollback()
    assert remaining == 0
