"""add measurements module tables (ADR-0051 §3)

Revision ID: c4a7e19d2b60
Revises: ea480577269c
Create Date: 2026-11-10 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c4a7e19d2b60"
down_revision: str | None = "ea480577269c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "measurements_leads",
        sa.Column("lead_id", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("pipeline_id", sa.BigInteger(), nullable=True),
        sa.Column("status_id", sa.BigInteger(), nullable=True),
        sa.Column("site_visit_enum_id", sa.BigInteger(), nullable=True),
        sa.Column("closed_at", _TIMESTAMP, nullable=True),
        sa.Column("price", sa.Numeric(12, 3), nullable=True),
        sa.Column("amo_updated_at", _TIMESTAMP, nullable=True),
        sa.Column("deleted_at", _TIMESTAMP, nullable=True),
        sa.Column("synced_at", _TIMESTAMP, nullable=False),
    )

    op.create_table(
        "measurements_visits",
        sa.Column("task_id", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("task_type_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("responsible_amo_user_id", sa.BigInteger(), nullable=False),
        sa.Column("scheduled_at", _TIMESTAMP, nullable=False),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("is_all_day", sa.Boolean(), nullable=False),
        sa.Column("is_completed", sa.Boolean(), nullable=False),
        sa.Column("completed_at", _TIMESTAMP, nullable=True),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column("amo_created_at", _TIMESTAMP, nullable=False),
        sa.Column("amo_updated_at", _TIMESTAMP, nullable=False),
        sa.Column("deleted_at", _TIMESTAMP, nullable=True),
        sa.Column("deleted_reason", sa.String(20), nullable=True),
        sa.Column("synced_at", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "kind IN ('primary', 'additional', 'legacy')", name="ck_measurements_visits_kind"
        ),
        sa.CheckConstraint(
            "deleted_reason IN ('deleted', 'retyped')",
            name="ck_measurements_visits_deleted_reason",
        ),
    )
    op.create_index(
        "ix_measurements_visits_lead_id_scheduled_at",
        "measurements_visits",
        ["lead_id", "scheduled_at"],
    )
    op.create_index("ix_measurements_visits_task_type_id", "measurements_visits", ["task_type_id"])

    op.create_table(
        "measurements_amo_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("occurred_at", _TIMESTAMP, nullable=False),
        sa.Column("amo_user_id", sa.BigInteger(), nullable=True),
        sa.Column("value_before", postgresql.JSONB(), nullable=True),
        sa.Column("value_after", postgresql.JSONB(), nullable=True),
        sa.Column("ingested_at", _TIMESTAMP, nullable=False),
    )
    op.create_index(
        "ix_measurements_amo_events_lead_id_occurred_at_event_id",
        "measurements_amo_events",
        ["lead_id", "occurred_at", "event_id"],
    )
    op.create_index(
        "ix_measurements_amo_events_entity",
        "measurements_amo_events",
        ["entity_type", "entity_id", "occurred_at", "event_id"],
    )
    op.create_index(
        "ix_measurements_amo_events_event_type_occurred_at",
        "measurements_amo_events",
        ["event_type", "occurred_at"],
    )

    field_values = op.create_table(
        "measurements_field_values",
        sa.Column("enum_id", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=True),
        sa.Column("visit_occurred", sa.Boolean(), nullable=True),
        sa.Column("outcome_type", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint(
            "outcome_type IN ('not_sold', 'completed', 'sold', 'declined')",
            name="ck_measurements_field_values_outcome_type",
        ),
    )
    op.bulk_insert(
        field_values,
        [
            {
                "enum_id": 627963,
                "label": "Closed, Not Sold On-Site",
                "visit_occurred": True,
                "outcome_type": "not_sold",
            },
            {
                "enum_id": 627965,
                "label": "Visit Completed",
                "visit_occurred": True,
                "outcome_type": "completed",
            },
            {
                "enum_id": 627967,
                "label": "Sold On-Site",
                "visit_occurred": True,
                "outcome_type": "sold",
            },
            {
                "enum_id": 627969,
                "label": "Declined Before Visit",
                "visit_occurred": False,
                "outcome_type": "declined",
            },
        ],
    )

    op.create_table(
        "measurements_result_attributions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", sa.String(64), nullable=True),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=True),
        sa.Column("rule", sa.String(32), nullable=False),
        sa.Column("deadline_source", sa.String(20), nullable=True),
        sa.Column("is_effective", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("computed_at", _TIMESTAMP, nullable=False),
        sa.UniqueConstraint("event_id", name="uq_measurements_result_attributions_event_id"),
        sa.CheckConstraint(
            "rule IN ('cleared', 'same_or_past', 'early_entry', 'upcoming', 'late_decline', "
            "'snapshot_fallback', 'unmapped', 'no_visit')",
            name="ck_measurements_result_attributions_rule",
        ),
        sa.CheckConstraint(
            "deadline_source IN ('history', 'current')",
            name="ck_measurements_result_attributions_deadline_source",
        ),
    )
    op.create_index(
        "ix_measurements_result_attributions_lead_id",
        "measurements_result_attributions",
        ["lead_id"],
    )
    op.create_index(
        "ix_measurements_result_attributions_task_id",
        "measurements_result_attributions",
        ["task_id"],
    )

    op.create_table(
        "measurements_sync_state",
        sa.Column("stream", sa.String(64), primary_key=True),
        sa.Column("watermark_at", _TIMESTAMP, nullable=True),
        sa.Column("last_attempt_at", _TIMESTAMP, nullable=True),
        sa.Column("last_success_at", _TIMESTAMP, nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("heartbeat_at", _TIMESTAMP, nullable=True),
        sa.Column(
            "counters",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "last_status IN ('ok', 'running', 'error', 'auth_failed', 'aborted')",
            name="ck_measurements_sync_state_last_status",
        ),
    )

    op.create_table(
        "measurements_user_access",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "granted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("granted_at", _TIMESTAMP, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "measurements_amo_users",
        sa.Column("amo_user_id", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("synced_at", _TIMESTAMP, nullable=False),
    )

    op.create_table(
        "measurements_pipeline_statuses",
        sa.Column("pipeline_id", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("status_id", sa.BigInteger(), autoincrement=False, primary_key=True),
        sa.Column("pipeline_name", sa.String(255), nullable=False),
        sa.Column("status_name", sa.String(255), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("synced_at", _TIMESTAMP, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("measurements_pipeline_statuses")
    op.drop_table("measurements_amo_users")
    op.drop_table("measurements_user_access")
    op.drop_table("measurements_sync_state")
    op.drop_table("measurements_result_attributions")
    op.drop_table("measurements_field_values")
    op.drop_table("measurements_amo_events")
    op.drop_table("measurements_visits")
    op.drop_table("measurements_leads")
