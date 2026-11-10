"""Backfill script (ADR-0051 §4, stage 7): dry-run by default, same advisory lock."""

import os

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.measurements.models import (
    MeasurementsAmoEvent,
    MeasurementsFieldValue,
    MeasurementsLead,
    MeasurementsResultAttribution,
    MeasurementsSyncState,
    MeasurementsVisit,
)
from app.measurements.scripts.backfill import main
from app.measurements.sync import INCREMENTAL_STREAMS, run_cycle
from app.measurements.worker import LOCK_BUSY_EXIT, acquire_lock, make_engine, release_lock
from tests.measurements.amo_fixtures import deadline_event, field_event, rows
from tests.measurements.test_sync import (
    ADDITIONAL,
    CUTOVER_TS,
    LEGACY,
    NAZAR,
    NOW,
    OTHER_USER,
    PRIMARY,
    T0,
    Env,
    lead_snapshot,
    make_task,
)

MATT = 14156562
DAY = 86400
WRITE_TABLES = (
    MeasurementsVisit,
    MeasurementsLead,
    MeasurementsAmoEvent,
    MeasurementsResultAttribution,
    MeasurementsSyncState,
)


@pytest.fixture
def engine():
    worker_engine = make_engine(os.environ["DATABASE_URL"])
    yield worker_engine
    worker_engine.dispose()


@pytest.fixture
def env(sync_tables_clean):
    with SessionLocal() as db:
        environment = Env(db)
        amo = environment.amo
        old = CUTOVER_TS - 400 * DAY
        # Legacy history: two measurers, one meeting of someone else, one contact task.
        amo.add_task(
            make_task(1, lead_id=101, task_type=LEGACY, created_at=old, complete_till=old + DAY)
        )
        amo.add_task(
            {
                **make_task(2, lead_id=102, task_type=LEGACY),
                "responsible_user_id": MATT,
                "created_at": old,
                "complete_till": old,
                "updated_at": old,
            }
        )
        amo.add_task(
            {**make_task(3, lead_id=103, task_type=LEGACY), "responsible_user_id": OTHER_USER}
        )
        amo.add_task({**make_task(4, lead_id=104, task_type=LEGACY), "entity_type": "contacts"})
        # Transition meeting and new types after cutover.
        amo.add_task(make_task(5, lead_id=105, task_type=LEGACY, complete_till=T0))
        amo.add_task(make_task(6, lead_id=105, task_type=PRIMARY, complete_till=T0 + DAY))
        amo.add_task(make_task(7, lead_id=106, task_type=ADDITIONAL, complete_till=T0))
        amo.events = [
            field_event("f1", 105, T0 + 60, None, 627965),
            field_event("f2", 106, T0 + 60, None, 999999),
            field_event("f3", 107, T0 + 60, None, 627967),
            deadline_event("d1", 6, T0 + 30, T0, T0 + DAY),
            {
                **rows("events_lead_status_changed.json", "events")[0],
                "id": "s1",
                "entity_id": 101,
                "created_at": old + 5,
            },
        ]
        for lead_id in (101, 102, 105, 106, 107):
            amo.leads[lead_id] = lead_snapshot(lead_id=lead_id, custom_fields_values=None)
        yield environment


def run(env, engine, *args: str) -> int:
    return main(
        list(args), settings=env.settings, engine=engine, client=env.client, now=lambda: NOW
    )


def counts() -> dict[str, int]:
    with SessionLocal() as db:
        return {
            model.__tablename__: db.scalar(select(func.count()).select_from(model))
            for model in WRITE_TABLES
        }


def printed(capsys) -> dict[str, str]:
    lines = capsys.readouterr().out.splitlines()
    return dict(line.split(": ", 1) for line in lines if ": " in line)


def test_dry_run_is_the_default_and_writes_nothing(env, engine, capsys):
    assert run(env, engine) == 0
    assert set(counts().values()) == {0}
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MeasurementsFieldValue)) == 4
    assert "DRY-RUN: nothing written" in capsys.readouterr().out


def test_dry_run_only_reads(env, engine):
    run(env, engine)
    assert {request.method for request in env.amo.requests} == {"GET"}


def test_dry_run_prints_the_counters(env, engine, capsys):
    run(env, engine)
    out = printed(capsys)
    assert out["tasks.kind.legacy"] == "3"
    assert out["tasks.kind.primary"] == "1"
    assert out["tasks.kind.additional"] == "1"
    assert out["tasks.measurer.Nazar"] == "4"
    assert out["tasks.measurer.Matt Measurement"] == "1"
    assert out["tasks.discarded_not_lead"] == "1"
    assert out["leads"] == "5"
    assert out["events.custom_field_784029_value_changed"] == "3"
    assert out["events.task_deadline_changed"] == "1"
    assert out["events.lead_status_changed"] == "1"
    assert out["transition_meetings_counted"] == "1"
    assert out["post_cutover_meeting_ignored"] == "0"
    assert out["unmapped"] == "1"
    assert out["no_visit"] == "1"
    assert out["drift"] == "3"


def test_legacy_is_read_in_full_and_new_types_from_cutover(env, engine):
    run(env, engine)
    tasks = env.amo.calls_to("/tasks")
    legacy = [call for call in tasks if call.url.params.get_list("filter[task_type][]") == ["2"]]
    new = [call for call in tasks if "4410970" in call.url.params.get_list("filter[task_type][]")]
    assert "filter[updated_at][from]" not in legacy[0].url.params
    assert new[0].url.params["filter[updated_at][from]"] == str(CUTOVER_TS)


def test_apply_writes_what_dry_run_counted(env, engine, capsys):
    run(env, engine)
    dry = printed(capsys)
    assert run(env, engine, "--apply") == 0
    applied = printed(capsys)
    ignored = ("mode", "DRY-RUN")
    assert {key: value for key, value in applied.items() if key not in ignored} == {
        key: value for key, value in dry.items() if key not in ignored
    }
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MeasurementsVisit)) == 5
        assert db.scalar(select(func.count()).select_from(MeasurementsLead)) == 5
        rules = dict(
            db.execute(
                select(MeasurementsResultAttribution.rule, func.count()).group_by(
                    MeasurementsResultAttribution.rule
                )
            ).all()
        )
    assert rules.get("unmapped") == int(dry["unmapped"])
    assert rules.get("no_visit") == int(dry["no_visit"])


def test_apply_sets_the_watermarks_of_every_polling_stream(env, engine):
    run(env, engine, "--apply")
    with SessionLocal() as db:
        for stream in INCREMENTAL_STREAMS:
            assert db.get(MeasurementsSyncState, stream).watermark_at == NOW, stream


def test_polling_streams_match_the_backfill_list(env):
    run_cycle(env.ctx)
    with SessionLocal() as db:
        names = set(db.scalars(select(MeasurementsSyncState.stream)).all())
    assert names == set(INCREMENTAL_STREAMS)


def test_backfill_waits_for_a_running_worker(env, engine, capsys):
    holder = acquire_lock(engine)
    try:
        assert run(env, engine, "--apply") == LOCK_BUSY_EXIT
    finally:
        release_lock(holder)
    assert "another measurements worker or backfill" in capsys.readouterr().err
    assert set(counts().values()) == {0}
    assert env.amo.requests == []


def test_worker_waits_for_a_running_backfill(env, engine):
    """The backfill holds the lock for its whole run; a worker started meanwhile exits."""
    seen = {}

    def worker_tries_during_backfill(request):
        if not seen:
            seen["lock"] = acquire_lock(engine)
        return None

    env.amo.fail_when = worker_tries_during_backfill
    run(env, engine)
    assert seen["lock"] is None
    after = acquire_lock(engine)
    assert after is not None
    release_lock(after)


def test_measurer_and_other_counts_use_the_map(env, engine, capsys):
    env.amo.add_task(make_task(8, lead_id=108, task_type=PRIMARY, responsible_user_id=OTHER_USER))
    run(env, engine)
    assert printed(capsys)["tasks.measurer.other"] == "1"
    assert NAZAR in env.settings.measurer_map
