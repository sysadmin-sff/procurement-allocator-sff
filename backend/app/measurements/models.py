"""Tables of the measurements module (ADR-0051 §3).

Imported unconditionally from `app.models` so that alembic sees these tables.
Must not import `app.models`: that package imports this module, and the cycle
would break whenever this module is imported first.

amo ids are natural `BigInteger` keys, because upserts run on them. There are
no foreign keys between sync tables: data arrives out of order.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

VISIT_KINDS = ("primary", "additional", "legacy")
DELETED_REASONS = ("deleted", "retyped")
OUTCOME_TYPES = ("not_sold", "completed", "sold", "declined")
ATTRIBUTION_RULES = (
    "cleared",
    "same_or_past",
    "early_entry",
    "upcoming",
    "late_decline",
    "snapshot_fallback",
    "unmapped",
    "no_visit",
)
DEADLINE_SOURCES = ("history", "current")
SYNC_STATUSES = ("ok", "running", "error", "auth_failed", "aborted")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class MeasurementsLead(Base):
    __tablename__ = "measurements_leads"

    lead_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    # NULL until the first /leads snapshot: an event can make a lead known earlier.
    pipeline_id: Mapped[int | None] = mapped_column(BigInteger)
    status_id: Mapped[int | None] = mapped_column(BigInteger)
    site_visit_enum_id: Mapped[int | None] = mapped_column(BigInteger)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    amo_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MeasurementsVisit(Base):
    __tablename__ = "measurements_visits"
    __table_args__ = (
        CheckConstraint(_one_of("kind", VISIT_KINDS), name="ck_measurements_visits_kind"),
        CheckConstraint(
            _one_of("deleted_reason", DELETED_REASONS),
            name="ck_measurements_visits_deleted_reason",
        ),
        Index("ix_measurements_visits_lead_id_scheduled_at", "lead_id", "scheduled_at"),
        Index("ix_measurements_visits_task_type_id", "task_type_id"),
    )

    task_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    lead_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    task_type_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    responsible_amo_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """Start of the visit: amo's `complete_till`."""
    duration: Mapped[int | None] = mapped_column(Integer)
    is_all_day: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_text: Mapped[str | None] = mapped_column(Text)
    """Stored, but the module's API never returns it in v1 (ADR-0051 §2)."""
    amo_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """Lets `kind` be reproduced from our data alone (ADR-0051, 2026-11-10)."""
    amo_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_reason: Mapped[str | None] = mapped_column(String(20))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MeasurementsAmoEvent(Base):
    """Append-only: rows are written with INSERT ... ON CONFLICT DO NOTHING."""

    __tablename__ = "measurements_amo_events"
    __table_args__ = (
        Index(
            "ix_measurements_amo_events_lead_id_occurred_at_event_id",
            "lead_id",
            "occurred_at",
            "event_id",
        ),
        Index(
            "ix_measurements_amo_events_entity",
            "entity_type",
            "entity_id",
            "occurred_at",
            "event_id",
        ),
        Index("ix_measurements_amo_events_event_type_occurred_at", "event_type", "occurred_at"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lead_id: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amo_user_id: Mapped[int | None] = mapped_column(BigInteger)
    value_before: Mapped[Any | None] = mapped_column(JSONB)
    value_after: Mapped[Any | None] = mapped_column(JSONB)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MeasurementsFieldValue(Base):
    """Sync updates `label`, `sort` and `is_active`, never the outcome mapping."""

    __tablename__ = "measurements_field_values"
    __table_args__ = (
        CheckConstraint(
            _one_of("outcome_type", OUTCOME_TYPES),
            name="ck_measurements_field_values_outcome_type",
        ),
    )

    enum_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    sort: Mapped[int | None] = mapped_column(Integer)
    visit_occurred: Mapped[bool | None] = mapped_column(Boolean)
    outcome_type: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class MeasurementsResultAttribution(Base):
    """Derived from a lead's history and fully recomputed."""

    __tablename__ = "measurements_result_attributions"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_measurements_result_attributions_event_id"),
        CheckConstraint(
            _one_of("rule", ATTRIBUTION_RULES), name="ck_measurements_result_attributions_rule"
        ),
        CheckConstraint(
            _one_of("deadline_source", DEADLINE_SOURCES),
            name="ck_measurements_result_attributions_deadline_source",
        ),
        Index("ix_measurements_result_attributions_lead_id", "lead_id"),
        Index("ix_measurements_result_attributions_task_id", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[str | None] = mapped_column(String(64))
    lead_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    task_id: Mapped[int | None] = mapped_column(BigInteger)
    rule: Mapped[str] = mapped_column(String(32), nullable=False)
    deadline_source: Mapped[str | None] = mapped_column(String(20))
    is_effective: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MeasurementsSyncState(Base):
    __tablename__ = "measurements_sync_state"
    __table_args__ = (
        CheckConstraint(
            _one_of("last_status", SYNC_STATUSES), name="ck_measurements_sync_state_last_status"
        ),
    )

    stream: Mapped[str] = mapped_column(String(64), primary_key=True)
    watermark_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(20))
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class MeasurementsUserAccess(Base):
    """A grant, deliberately not a value of `User.role` (ADR-0051 §2)."""

    __tablename__ = "measurements_user_access"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MeasurementsAmoUser(Base):
    __tablename__ = "measurements_amo_users"

    amo_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MeasurementsPipelineStatus(Base):
    """Composite key: statuses 142/143 exist in every pipeline."""

    __tablename__ = "measurements_pipeline_statuses"

    pipeline_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    status_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    pipeline_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort: Mapped[int | None] = mapped_column(Integer)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
