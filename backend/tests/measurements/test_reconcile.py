"""Nightly reconciliation (ADR-0051 §4): deleted vs retyped, 5% fuse, kind recompute."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.measurements.config import MeasurementsSettings
from app.measurements.models import (
    MeasurementsFieldValue,
    MeasurementsLead,
    MeasurementsResultAttribution,
    MeasurementsVisit,
)
from app.measurements.reconcile import run_reconcile
from tests.measurements.amo_fixtures import field_event
from tests.measurements.test_sync import (
    LEGACY,
    NOW,
    PRIMARY,
    T0,
    Env,
    lead_snapshot,
    make_task,
)

COUNT = 40
FIRST_TASK = 700000
FIRST_LEAD = 800000


@pytest.fixture
def env(sync_tables_clean):
    with SessionLocal() as db:
        environment = Env(db)
        for number in range(COUNT):
            task_type = LEGACY if number < 10 else PRIMARY
            environment.amo.add_task(
                make_task(
                    task_id=FIRST_TASK + number,
                    lead_id=FIRST_LEAD + number,
                    task_type=task_type,
                )
            )
            environment.amo.leads[FIRST_LEAD + number] = lead_snapshot(lead_id=FIRST_LEAD + number)
        environment.cycle()
        environment.now = NOW + timedelta(hours=16)
        yield environment


def reconcile(env) -> None:
    run_reconcile(env.ctx)
    env.db.expire_all()


def active_visits(env) -> int:
    return env.db.scalar(
        select(func.count())
        .select_from(MeasurementsVisit)
        .where(MeasurementsVisit.deleted_at.is_(None))
    )


def test_missing_task_that_no_longer_exists_is_deleted(env):
    del env.amo.tasks[FIRST_TASK + 20]
    reconcile(env)
    visit = env.visit(FIRST_TASK + 20)
    assert visit.deleted_reason == "deleted"
    assert visit.deleted_at == env.now
    assert env.state("reconcile").last_status == "ok"


def test_missing_task_with_another_type_is_retyped(env):
    task = env.amo.tasks[FIRST_TASK + 21]
    env.amo.tasks[FIRST_TASK + 21] = {**task, "task_type_id": 1, "updated_at": T0 + 50}
    reconcile(env)
    visit = env.visit(FIRST_TASK + 21)
    assert visit.deleted_reason == "retyped"
    assert visit.task_type_id == 1


def test_reconcile_tells_deleted_and_retyped_apart_in_one_run(env):
    del env.amo.tasks[FIRST_TASK + 20]
    task = env.amo.tasks[FIRST_TASK + 21]
    env.amo.tasks[FIRST_TASK + 21] = {**task, "task_type_id": 1, "updated_at": T0 + 50}
    reconcile(env)
    assert env.visit(FIRST_TASK + 20).deleted_reason == "deleted"
    assert env.visit(FIRST_TASK + 21).deleted_reason == "retyped"
    counters = env.state("reconcile").counters
    assert counters["deleted"] == 1
    assert counters["retyped"] == 1


def test_fuse_aborts_without_writing_when_amo_lists_nothing(env):
    env.amo.tasks.clear()
    reconcile(env)
    state = env.state("reconcile")
    assert state.last_status == "aborted"
    assert state.counters["visit_removals"] == COUNT
    assert active_visits(env) == COUNT
    assert env.amo.calls_to(f"/tasks/{FIRST_TASK}") == []


def test_fuse_trips_just_above_five_percent(env):
    for number in (20, 21, 22):  # 3 of 40 = 7.5%
        del env.amo.tasks[FIRST_TASK + number]
    reconcile(env)
    assert env.state("reconcile").last_status == "aborted"
    assert active_visits(env) == COUNT


def test_fuse_allows_exactly_five_percent(env):
    for number in (20, 21):  # 2 of 40 = 5%
        del env.amo.tasks[FIRST_TASK + number]
    reconcile(env)
    assert env.state("reconcile").last_status == "ok"
    assert active_visits(env) == COUNT - 2


def test_fuse_covers_leads(env):
    for number in range(5):
        del env.amo.leads[FIRST_LEAD + 20 + number]
    reconcile(env)
    assert env.state("reconcile").last_status == "aborted"
    assert env.db.get(MeasurementsLead, FIRST_LEAD + 20).deleted_at is None


def test_lead_gone_from_amo_is_marked_deleted(env):
    del env.amo.leads[FIRST_LEAD + 20]
    reconcile(env)
    assert env.db.get(MeasurementsLead, FIRST_LEAD + 20).deleted_at == env.now


def test_config_reclassification_past_five_percent_is_applied(env):
    env.settings = MeasurementsSettings(
        _env_file=None, legacy_meetings_until=datetime.fromtimestamp(T0 - 10, timezone.utc)
    )
    reconcile(env)  # 10 of 40 rows = 25%, all caused by the config change
    state = env.state("reconcile")
    assert state.last_status == "ok"
    assert state.counters["reclassified_retyped"] == 10
    assert state.counters["visit_removals"] == 0
    assert active_visits(env) == COUNT - 10


def test_config_reclassification_applies_even_when_amo_answers_trip_the_fuse(env):
    env.settings = MeasurementsSettings(
        _env_file=None, legacy_meetings_until=datetime.fromtimestamp(T0 - 10, timezone.utc)
    )
    for number in range(20, 40):
        del env.amo.tasks[FIRST_TASK + number]
    reconcile(env)
    state = env.state("reconcile")
    assert state.last_status == "aborted"
    assert state.counters["reclassified_retyped"] == 10
    assert env.visit(FIRST_TASK).deleted_reason == "retyped"
    assert env.visit(FIRST_TASK + 20).deleted_at is None


def test_closing_the_transition_recomputes_kind(env):
    env.settings = MeasurementsSettings(
        _env_file=None, legacy_meetings_until=datetime.fromtimestamp(T0 - 10, timezone.utc)
    )
    reconcile(env)
    assert env.visit(FIRST_TASK).deleted_reason == "retyped"
    assert env.visit(FIRST_TASK + 10).deleted_at is None
    assert env.state("reconcile").counters["post_cutover_meeting_ignored"] == 10


def test_kind_is_recomputed_from_our_data_when_amo_is_down(env):
    env.settings = MeasurementsSettings(
        _env_file=None, legacy_meetings_until=datetime.fromtimestamp(T0 - 10, timezone.utc)
    )
    env.amo.fail_when = lambda request: httpx.Response(503)
    reconcile(env)
    assert env.visit(FIRST_TASK).deleted_reason == "retyped"
    state = env.state("reconcile")
    assert state.last_status == "error"
    assert state.last_http_status == 503


def test_reopening_the_transition_restores_from_our_data(env):
    test_kind_is_recomputed_from_our_data_when_amo_is_down(env)
    env.settings = MeasurementsSettings(_env_file=None)
    env.amo.fail_when = lambda request: httpx.Response(503)
    reconcile(env)
    visit = env.visit(FIRST_TASK)
    assert visit.deleted_at is None
    assert visit.deleted_reason is None


def test_transition_meetings_are_counted(env):
    reconcile(env)
    assert env.state("reconcile").counters["transition_meetings_counted"] == 10


def test_reconcile_recomputes_attribution_after_a_mapping_change(env):
    lead_id = FIRST_LEAD + 30
    env.amo.events = [field_event("e-map", lead_id, T0 + 60, None, 627967)]
    env.state("events_field").watermark_at = datetime.fromtimestamp(T0, timezone.utc)
    env.db.commit()
    env.now = NOW + timedelta(minutes=5)
    env.cycle()
    row = env.db.get(MeasurementsFieldValue, 627967)
    row.visit_occurred = None
    env.db.commit()
    env.now = NOW + timedelta(hours=16)
    reconcile(env)
    rule = env.db.scalar(
        select(MeasurementsResultAttribution.rule).where(
            MeasurementsResultAttribution.event_id == "e-map"
        )
    )
    assert rule == "unmapped"
