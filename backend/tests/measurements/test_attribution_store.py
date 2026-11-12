"""Writing attributions and recomputing them from synced data (ADR-0051 §3)."""

import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.measurements.attribution import RULE_VERSION
from app.measurements.attribution_store import recompute_lead
from app.measurements.models import (
    MeasurementsAmoEvent,
    MeasurementsFieldValue,
    MeasurementsLead,
    MeasurementsResultAttribution,
    MeasurementsVisit,
)
from tests.measurements.amo_fixtures import deadline_event, field_event, rows
from tests.measurements.conftest import _reset_sync_tables
from tests.measurements.test_sync import (
    ADDITIONAL,
    CUTOVER_TS,
    LEAD,
    LEGACY,
    NOW,
    PRIMARY,
    T0,
    TASK,
    Env,
    lead_snapshot,
    make_task,
    type_changed,
)

SOLD = 627967
COMPLETED = 627965
DAY = 86400


@pytest.fixture
def env(sync_tables_clean):
    with SessionLocal() as db:
        yield Env(db)


def visit_task(task_id=TASK, task_type=PRIMARY, complete_till=T0 + DAY, **overrides) -> dict:
    return {
        **make_task(task_id=task_id, task_type=task_type),
        "complete_till": complete_till,
        **overrides,
    }


def attributions(env) -> dict:
    env.db.expire_all()
    found = env.db.scalars(select(MeasurementsResultAttribution)).all()
    return {row.event_id: row for row in found}


def shape(env) -> set[tuple]:
    return {
        (row.event_id, row.lead_id, row.task_id, row.rule, row.deadline_source, row.is_effective)
        for row in attributions(env).values()
    }


def move_watermarks_back(env) -> None:
    for stream in ("events_task_deleted", "events_task_type"):
        env.state(stream).watermark_at = datetime.fromtimestamp(T0, timezone.utc)
        env.db.commit()  # env.state() expires the session, dropping uncommitted edits


def test_cycle_writes_the_attribution(env):
    env.amo.add_task(visit_task(complete_till=T0))
    env.amo.events = [field_event("e1", LEAD, T0 + 60, None, SOLD)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    row = attributions(env)["e1"]
    assert (row.lead_id, row.task_id, row.rule) == (LEAD, TASK, "same_or_past")
    assert row.is_effective is True
    assert row.rule_version == RULE_VERSION
    assert row.computed_at == NOW


def test_recomputing_gives_the_same_rows(env):
    env.amo.add_task(visit_task(complete_till=T0))
    env.amo.events = [field_event("e1", LEAD, T0 + 60, None, SOLD)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    before = shape(env)
    env.now = NOW + timedelta(minutes=5)
    recompute_lead(env.db, LEAD, env.settings, env.now)
    env.db.commit()
    assert shape(env) == before


def test_recompute_replaces_old_rows(env):
    env.amo.add_task(visit_task(complete_till=T0))
    env.amo.events = [field_event("e1", LEAD, T0 + 60, None, SOLD)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    recompute_lead(env.db, LEAD, env.settings, NOW)
    recompute_lead(env.db, LEAD, env.settings, NOW)
    env.db.commit()
    assert len(attributions(env)) == 1


def test_recompute_does_not_commit(env):
    env.amo.add_task(visit_task(complete_till=T0))
    env.amo.events = [field_event("e1", LEAD, T0 + 60, None, SOLD)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    env.db.delete(env.db.get(MeasurementsVisit, TASK))
    env.db.flush()
    recompute_lead(env.db, LEAD, env.settings, NOW)
    env.db.rollback()
    assert attributions(env)["e1"].task_id == TASK


def test_deleting_a_task_moves_the_result(env):
    env.amo.add_task(visit_task(complete_till=T0))
    env.amo.add_task(visit_task(task_id=TASK + 1, task_type=ADDITIONAL, complete_till=T0 + 30))
    env.amo.events = [field_event("e1", LEAD, T0 + 60, None, SOLD)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    assert attributions(env)["e1"].task_id == TASK + 1

    env.amo.events.append(
        {
            **rows("events_task_deleted.json", "events")[0],
            "id": "evt-del",
            "entity_id": TASK + 1,
            "created_at": T0 + 90,
        }
    )
    env.now = NOW + timedelta(minutes=5)
    move_watermarks_back(env)
    env.cycle()
    assert attributions(env)["e1"].task_id == TASK


def test_retyping_a_task_moves_the_result(env):
    env.amo.add_task(visit_task(complete_till=T0))
    env.amo.add_task(visit_task(task_id=TASK + 1, task_type=ADDITIONAL, complete_till=T0 + 30))
    env.amo.events = [field_event("e1", LEAD, T0 + 60, None, SOLD)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()

    env.amo.add_task({**visit_task(task_id=TASK + 1, task_type=1), "updated_at": T0 + 90})
    env.amo.events.append(type_changed("evt-type", TASK + 1, T0 + 90, 1))
    env.now = NOW + timedelta(minutes=5)
    move_watermarks_back(env)
    env.cycle()
    assert attributions(env)["e1"].task_id == TASK


def test_transition_meeting_gets_a_result_and_stays_legacy(env):
    env.amo.add_task(visit_task(task_type=LEGACY, complete_till=T0))
    env.amo.events = [field_event("e1", LEAD, T0 + 60, None, SOLD)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    assert attributions(env)["e1"].task_id == TASK
    assert env.visit().kind == "legacy"


def test_legacy_visit_before_cutover_gets_no_result(env):
    env.amo.add_task(visit_task(task_type=LEGACY, complete_till=CUTOVER_TS - DAY))
    env.amo.events = [field_event("e1", LEAD, T0 + 60, None, SOLD)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    row = attributions(env)["e1"]
    assert (row.rule, row.task_id) == ("no_visit", None)
    assert env.state("attribution").counters["no_visit"] == 1


def test_only_field_events_are_used(env):
    env.amo.add_task(visit_task(complete_till=T0))
    env.amo.leads[LEAD] = lead_snapshot(custom_fields_values=None)
    status = {
        **rows("events_lead_status_changed.json", "events")[0],
        "id": "evt-status",
        "entity_id": LEAD,
        "created_at": T0 + 1,
    }
    env.amo.events = [status]
    env.cycle()
    assert env.db.get(MeasurementsAmoEvent, "evt-status") is not None
    assert attributions(env) == {}


def test_deadline_events_are_read_from_the_store(env):
    env.amo.add_task(visit_task(complete_till=T0 + 10 * DAY))
    env.amo.events = [
        field_event("e1", LEAD, T0 + 60, None, 627969),
        deadline_event("d1", TASK, T0 + 120, T0 + 5 * DAY, T0 + 10 * DAY),
    ]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    row = attributions(env)["e1"]
    assert (row.rule, row.deadline_source) == ("upcoming", "history")


def test_new_enum_without_mapping_is_unmapped(env):
    env.db.add(MeasurementsFieldValue(enum_id=999111, label="New"))
    env.db.commit()
    env.amo.add_task(visit_task(complete_till=T0))
    env.amo.events = [field_event("e1", LEAD, T0 + 60, None, 999111)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    assert attributions(env)["e1"].rule == "unmapped"
    assert env.state("attribution").counters["unmapped"] == 1


def test_snapshot_fallback_uses_the_lead_row(env):
    env.amo.add_task(visit_task(complete_till=T0))
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    row = attributions(env)[None]
    assert (row.rule, row.task_id, row.event_id) == ("snapshot_fallback", TASK, None)


def test_drift_is_counted(env):
    env.amo.add_task(visit_task(complete_till=T0))
    env.amo.events = [field_event("e1", LEAD, T0 + 60, None, COMPLETED)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    assert env.state("attribution").counters["drift"] == 1


def test_lead_without_a_row_is_skipped_cleanly(env):
    assert env.db.get(MeasurementsLead, 424242) is None
    recompute_lead(env.db, 424242, env.settings, NOW)
    env.db.rollback()
    assert attributions(env) == {}


def test_unchanged_leads_are_not_recomputed(env):
    env.amo.add_task(visit_task(complete_till=T0))
    env.amo.events = [field_event("e1", LEAD, T0 + 60, None, SOLD)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    first = attributions(env)["e1"].computed_at
    env.now = NOW + timedelta(hours=1)
    env.cycle()
    assert attributions(env)["e1"].computed_at == first


def test_ambiguous_decline_is_counted(env):
    env.amo.add_task(visit_task(complete_till=T0 + 10 * DAY))
    env.amo.events = [
        field_event("e1", LEAD, T0 + 60, None, SOLD),
        field_event("e2", LEAD, T0 + 120, SOLD, 627969),
    ]
    env.amo.leads[LEAD] = lead_snapshot(
        custom_fields_values=[
            {
                **rows("leads.json", "leads")[0]["custom_fields_values"][0],
                "values": [{"value": "Declined Before Visit", "enum_id": 627969}],
            }
        ]
    )
    env.cycle()
    assert attributions(env)["e2"].rule == "ambiguous_decline"
    assert env.state("attribution").counters["ambiguous_decline"] == 1


def _history_events() -> list[dict]:
    return [
        field_event("e1", LEAD, T0 + 60, None, COMPLETED),
        field_event("e2", LEAD, T0 + 60, COMPLETED, SOLD),
        field_event("e3", LEAD, T0 + 3 * DAY, SOLD, 627969),
        field_event("e4", LEAD, T0 + 4 * DAY, 627969, None),
        field_event("e5", LEAD, T0 + 5 * DAY, None, 627963),
        deadline_event("d1", TASK + 1, T0 + 30, T0 + 2 * DAY, T0 + 6 * DAY),
        deadline_event("d2", TASK + 1, T0 + 30, T0 + 6 * DAY, T0 + 7 * DAY),
    ]


def _synced_shape(seed: int | None) -> set[tuple]:
    _reset_sync_tables()
    with SessionLocal() as db:
        env = Env(db)
        tasks = [
            visit_task(complete_till=T0),
            visit_task(task_id=TASK + 1, task_type=ADDITIONAL, complete_till=T0 + 7 * DAY),
            visit_task(task_id=TASK + 2, task_type=LEGACY, complete_till=T0 + 5 * DAY),
        ]
        events = _history_events()
        if seed is not None:
            shuffler = random.Random(seed)
            shuffler.shuffle(tasks)
            shuffler.shuffle(events)
        for item in tasks:
            env.amo.add_task(item)
        env.amo.events = events
        env.amo.leads[LEAD] = lead_snapshot()
        env.cycle()
        return shape(env)


@pytest.mark.parametrize("seed", [3, 11, 99])
def test_synced_recompute_does_not_depend_on_arrival_order(sync_tables_clean, seed):
    expected = _synced_shape(None)
    assert len(expected) == 5
    assert _synced_shape(seed) == expected
