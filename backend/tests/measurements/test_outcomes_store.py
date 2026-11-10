"""Visit outcomes written by every write path, and holes Д1–Д3 (ADR-0053 §3).

One test per row of the write-path table: after the path runs, the lead's
outcome rows are current. Real test database, fake amo.
"""

import os
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from app.auth.cookies import SESSION_COOKIE
from app.core.database import SessionLocal
from app.measurements import attribution_store
from app.measurements.attribution_store import recompute_lead
from app.measurements.config import MeasurementsSettings
from app.measurements.models import (
    MeasurementsLead,
    MeasurementsResultAttribution,
    MeasurementsVisit,
    MeasurementsVisitOutcome,
)
from app.measurements.outcomes import OUTCOME_RULE_VERSION
from app.measurements.reconcile import run_reconcile
from app.measurements.scripts import recompute as recompute_module
from app.measurements.scripts.backfill import main as backfill_main
from app.measurements.scripts.recompute import main as recompute_main
from app.measurements.worker import LOCK_BUSY_EXIT, acquire_lock, make_engine, release_lock
from tests.measurements.amo_fixtures import field_event, rows
from tests.measurements.test_sync import (
    CUTOVER_TS,
    LEAD,
    LEGACY,
    NAZAR,
    NOW,
    OTHER_USER,
    PRIMARY,
    T0,
    TASK,
    Env,
    lead_snapshot,
    make_task,
    type_changed,
)

M, Q, SALES, OTHER_PIPELINE = 8740486, 8740374, 8740490, 8740510
M_STAGE = 70000001
DAY = 86400
FUNNEL_TILL = CUTOVER_TS - 5 * DAY
"""A legacy visit before the cutover: its outcome comes from the funnel."""
LATER = int(NOW.timestamp()) + 60
"""Inside the next polling window, which starts 2 minutes before NOW."""
COMPLETED, SOLD, DECLINED = 627965, 627967, 627969


def status_raw(event_id, lead_id, created_at, after, before=(M, M_STAGE)) -> dict:
    def side(pipeline_status):
        return [{"lead_status": {"pipeline_id": pipeline_status[0], "id": pipeline_status[1]}}]

    return {
        **rows("events_lead_status_changed.json", "events")[0],
        "id": event_id,
        "entity_id": lead_id,
        "created_at": created_at,
        "value_before": side(before),
        "value_after": side(after),
    }


def task_raw(fixture, event_id, task_id, created_at) -> dict:
    return {
        **rows(fixture, "events")[0],
        "id": event_id,
        "entity_id": task_id,
        "created_at": created_at,
    }


def legacy_task(task_id=TASK, lead_id=LEAD, complete_till=FUNNEL_TILL, **overrides) -> dict:
    return make_task(
        task_id=task_id,
        lead_id=lead_id,
        task_type=LEGACY,
        complete_till=complete_till,
        **overrides,
    )


def outcomes(db) -> dict[int, MeasurementsVisitOutcome]:
    db.expire_all()
    return {row.task_id: row for row in db.scalars(select(MeasurementsVisitOutcome)).all()}


def attribution_count(db, lead_id=LEAD) -> int:
    return db.scalar(
        select(func.count())
        .select_from(MeasurementsResultAttribution)
        .where(MeasurementsResultAttribution.lead_id == lead_id)
    )


def shape(db) -> set[tuple]:
    return {
        (
            row.task_id,
            row.lead_id,
            row.measurer_key,
            row.local_date,
            row.group_task_id,
            row.is_duplicate,
            row.result_source,
            row.funnel_outcome,
            row.no_data_reason,
            row.funnel_exit_event_id,
            row.site_visit_outcome,
            row.rule_version,
        )
        for row in outcomes(db).values()
    }


def next_cycle(env) -> None:
    env.now = env.now + timedelta(minutes=5)
    env.cycle()


@pytest.fixture
def env(sync_tables_clean):
    with SessionLocal() as db:
        yield Env(db)


# --- one test per write path (ADR-0053 §3 table)


def test_path_ingest_task_writes_the_outcome(env):
    env.amo.add_task(legacy_task())
    env.amo.events = [status_raw("s1", LEAD, FUNNEL_TILL + 3600, (M, 142))]
    env.amo.leads[LEAD] = lead_snapshot(pipeline_id=SALES)
    env.cycle()
    row = outcomes(env.db)[TASK]
    assert (row.result_source, row.funnel_outcome, row.funnel_exit_event_id) == (
        "funnel",
        "produced",
        "s1",
    )
    assert (row.measurer_key, row.group_task_id, row.is_duplicate) == ("Nazar", TASK, False)
    assert (row.rule_version, row.computed_at) == (OUTCOME_RULE_VERSION, NOW)


def test_path_mark_retyped_removes_the_outcome(env):
    env.amo.add_task(legacy_task())
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    assert TASK in outcomes(env.db)
    env.amo.add_task(legacy_task(responsible_user_id=OTHER_USER, updated_at=LATER))
    next_cycle(env)
    assert env.visit().deleted_reason == "retyped"
    assert outcomes(env.db) == {}


def test_path_field_event_updates_the_site_visit_outcome(env):
    env.amo.add_task(make_task(complete_till=T0))
    env.amo.leads[LEAD] = lead_snapshot(custom_fields_values=None)
    env.cycle()
    assert outcomes(env.db)[TASK].site_visit_outcome is None
    env.amo.events.append(field_event("f1", LEAD, LATER, None, COMPLETED))
    next_cycle(env)
    row = outcomes(env.db)[TASK]
    assert (row.result_source, row.site_visit_outcome) == ("site_visit", "completed")


def test_path_status_event_updates_the_funnel_outcome(env):
    env.amo.add_task(legacy_task())
    env.amo.leads[LEAD] = lead_snapshot(pipeline_id=OTHER_PIPELINE)
    env.cycle()
    row = outcomes(env.db)[TASK]
    assert (row.funnel_outcome, row.no_data_reason) == ("no_data", "never_in_measurements")
    env.amo.events.append(status_raw("s1", LEAD, LATER, (Q, 70000002)))
    next_cycle(env)
    row = outcomes(env.db)[TASK]
    assert (row.funnel_outcome, row.funnel_exit_event_id) == ("not_held", "s1")


def test_path_task_deleted_removes_the_outcome(env):
    env.amo.add_task(legacy_task())
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    env.amo.events.append(task_raw("events_task_deleted.json", "d1", TASK, LATER))
    next_cycle(env)
    assert env.visit().deleted_reason == "deleted"
    assert outcomes(env.db) == {}


def test_path_task_completed_recomputes_the_lead(env):
    env.amo.add_task(legacy_task(is_completed=True))
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    env.amo.events.append(task_raw("events_task_completed.json", "c1", TASK, LATER))
    next_cycle(env)
    row = outcomes(env.db)[TASK]
    assert row.computed_at == env.now
    assert row.funnel_outcome == "no_data"


def test_path_task_type_changed_removes_the_outcome(env):
    env.amo.add_task(legacy_task())
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    env.amo.add_task(legacy_task(task_type_id=1, updated_at=LATER))
    env.amo.events.append(type_changed("t1", TASK, LATER, 1))
    next_cycle(env)
    assert env.visit().deleted_reason == "retyped"
    assert outcomes(env.db) == {}


def test_path_leads_stream_snapshot_reaches_the_outcome(env):
    env.amo.add_task(legacy_task())
    env.cycle()  # amo has no snapshot of the lead yet
    assert outcomes(env.db)[TASK].no_data_reason == "never_in_measurements"
    env.amo.leads[LEAD] = lead_snapshot(pipeline_id=M, status_id=M_STAGE, updated_at=LATER)
    next_cycle(env)  # a lead without a snapshot is read again on every cycle
    assert env.lead().pipeline_id == M
    assert outcomes(env.db)[TASK].no_data_reason == "window"


RECONCILE_LEADS = 30
FIRST_TASK = 700000
FIRST_LEAD = 800000


@pytest.fixture
def many(env):
    """Enough rows that one removal stays under the 5% fuse."""
    for number in range(RECONCILE_LEADS):
        env.amo.add_task(
            make_task(
                task_id=FIRST_TASK + number,
                lead_id=FIRST_LEAD + number,
                task_type=PRIMARY if number >= 20 else LEGACY,
                responsible_user_id=OTHER_USER if number == 29 else NAZAR,
                complete_till=T0 + DAY if number >= 20 else FUNNEL_TILL,
            )
        )
        env.amo.leads[FIRST_LEAD + number] = lead_snapshot(lead_id=FIRST_LEAD + number)
    env.cycle()
    env.now = NOW + timedelta(hours=16)
    return env


def reconcile(env) -> None:
    run_reconcile(env.ctx)
    env.db.expire_all()


def test_path_reconcile_reclassification_removes_the_outcome(many):
    many.settings = MeasurementsSettings(_env_file=None, measurer_map={14156562: "Matt"})
    reconcile(many)
    assert many.state("reconcile").last_status == "ok"
    assert many.visit(FIRST_TASK).deleted_reason == "retyped"
    found = outcomes(many.db)
    assert FIRST_TASK not in found
    # Primary visits stay; Nazar is no longer in the map, so their key is NULL.
    assert found[FIRST_TASK + 20].measurer_key is None


def test_path_reconcile_listing_and_snapshots_update_the_outcome(many):
    del many.amo.tasks[FIRST_TASK + 1]  # gone from amo: deleted
    del many.amo.leads[FIRST_LEAD + 2]  # lead gone from amo: lead deleted
    reconcile(many)
    assert many.state("reconcile").last_status == "ok"
    assert many.visit(FIRST_TASK + 1).deleted_reason == "deleted"
    assert many.lead(FIRST_LEAD + 2).deleted_at == many.now
    found = outcomes(many.db)
    assert FIRST_TASK + 1 not in found
    assert FIRST_TASK + 2 not in found
    assert len(found) == RECONCILE_LEADS - 2
    assert {row.computed_at for row in found.values()} == {many.now}


def test_path_backfill_apply_writes_the_outcome(env):
    env.amo.add_task(legacy_task(task_id=1, lead_id=101, created_at=FUNNEL_TILL - DAY))
    env.amo.events = [status_raw("s1", 101, FUNNEL_TILL + 600, (M, 143))]
    env.amo.leads[101] = lead_snapshot(lead_id=101, custom_fields_values=None)
    engine = make_engine(os.environ["DATABASE_URL"])
    try:
        code = backfill_main(
            ["--apply"], settings=env.settings, engine=engine, client=env.client, now=lambda: NOW
        )
    finally:
        engine.dispose()
    assert code == 0
    row = outcomes(env.db)[1]
    assert (row.funnel_outcome, row.funnel_exit_event_id) == ("closed", "s1")


# --- Д1: the fuse no longer stops config changes from reaching derived rows


def test_fuse_recomputes_every_lead_with_the_new_map_and_cutover(many):
    before = outcomes(many.db)
    assert before[FIRST_TASK + 29].measurer_key is None
    assert before[FIRST_TASK + 21].result_source == "site_visit"
    many.settings = MeasurementsSettings(
        _env_file=None,
        measurer_map={NAZAR: "Nazar", OTHER_USER: "Newcomer"},
        cutover_at=datetime.fromtimestamp(T0 + 2 * DAY, timezone.utc),
    )
    many.amo.tasks.clear()  # every visit would be removed: the fuse trips
    reconcile(many)
    state = many.state("reconcile")
    assert state.last_status == "aborted"
    assert state.counters["recomputed"] == RECONCILE_LEADS
    after = outcomes(many.db)
    assert after[FIRST_TASK + 29].measurer_key == "Newcomer"
    assert {after[FIRST_TASK + n].result_source for n in range(20, 30)} == {"funnel"}
    assert {row.computed_at for row in after.values()} == {many.now}


# --- Д2 and the store-level rows of §6: L9, L22, L26


def _seed_lead_with_result(env) -> None:
    env.amo.add_task(make_task(complete_till=T0))
    env.amo.events = [field_event("f1", LEAD, T0 + 60, None, SOLD)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    assert TASK in outcomes(env.db)
    assert attribution_count(env.db) == 1


def test_l22_excluded_lead_loses_its_derived_rows(env):
    _seed_lead_with_result(env)
    env.settings = MeasurementsSettings(_env_file=None, excluded_lead_ids=frozenset({LEAD}))
    recompute_lead(env.db, LEAD, env.settings, NOW)
    env.db.commit()
    assert outcomes(env.db) == {}
    assert attribution_count(env.db) == 0


def test_l26_deleted_lead_loses_its_derived_rows_and_regains_them(env):
    _seed_lead_with_result(env)
    env.db.execute(
        update(MeasurementsLead).where(MeasurementsLead.lead_id == LEAD).values(deleted_at=NOW)
    )
    recompute_lead(env.db, LEAD, env.settings, NOW)
    env.db.commit()
    assert outcomes(env.db) == {}
    assert attribution_count(env.db) == 0

    env.db.execute(
        update(MeasurementsLead).where(MeasurementsLead.lead_id == LEAD).values(deleted_at=None)
    )
    recompute_lead(env.db, LEAD, env.settings, NOW)
    env.db.commit()
    assert outcomes(env.db)[TASK].site_visit_outcome == "sold"
    assert attribution_count(env.db) == 1


def test_l9_deleted_and_retyped_visits_have_no_rows(env):
    env.amo.add_task(legacy_task(task_id=91))
    env.amo.add_task(legacy_task(task_id=92, complete_till=FUNNEL_TILL + DAY))
    env.amo.add_task(legacy_task(task_id=93, complete_till=FUNNEL_TILL + 2 * DAY))
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    for task_id, reason in ((91, "deleted"), (92, "retyped")):
        env.db.execute(
            update(MeasurementsVisit)
            .where(MeasurementsVisit.task_id == task_id)
            .values(deleted_at=NOW, deleted_reason=reason)
        )
    recompute_lead(env.db, LEAD, env.settings, NOW)
    env.db.commit()
    assert set(outcomes(env.db)) == {93}


# --- recompute_lead itself


def test_recompute_is_idempotent(env):
    env.amo.add_task(legacy_task())
    env.amo.add_task(legacy_task(task_id=TASK + 1, complete_till=FUNNEL_TILL + 600))
    env.amo.events = [status_raw("s1", LEAD, FUNNEL_TILL + 3600, (M, 142))]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    before = shape(env.db)
    assert {row[5] for row in before} == {False, True}  # one group with a duplicate
    recompute_lead(env.db, LEAD, env.settings, NOW + timedelta(hours=1))
    env.db.commit()
    assert shape(env.db) == before


def test_attributions_and_outcomes_are_one_transaction(env):
    _seed_lead_with_result(env)
    env.db.execute(
        update(MeasurementsLead).where(MeasurementsLead.lead_id == LEAD).values(deleted_at=NOW)
    )
    recompute_lead(env.db, LEAD, env.settings, NOW)
    env.db.rollback()
    assert TASK in outcomes(env.db)
    assert attribution_count(env.db) == 1


def test_snapshot_result_is_the_effective_site_visit_outcome(env):
    env.amo.add_task(make_task(complete_till=T0))
    env.amo.leads[LEAD] = lead_snapshot(
        custom_fields_values=[{"field_id": 784029, "values": [{"enum_id": SOLD}]}]
    )
    env.cycle()
    assert outcomes(env.db)[TASK].site_visit_outcome == "sold"


# --- the group's Site Visit Result (ADR-0053, "Уточнения реализации")


def _two_visits_one_day(env, field_at, enum_id) -> dict:
    """Two primary visits of Nazar on 2026-11-09 NY, at T0 and T0 + 10 min."""
    env.amo.add_task(make_task(task_id=TASK, complete_till=T0))
    env.amo.add_task(make_task(task_id=TASK + 1, complete_till=T0 + 600))
    env.amo.events = [field_event("f1", LEAD, field_at, None, enum_id)]
    env.amo.leads[LEAD] = lead_snapshot(custom_fields_values=None)
    env.cycle()
    attribution = env.db.scalar(
        select(MeasurementsResultAttribution).where(MeasurementsResultAttribution.event_id == "f1")
    )
    return {"attributed_to": attribution.task_id, "rows": outcomes(env.db)}


def test_result_set_after_both_visits_lands_on_the_second_and_the_group_shows_it(env):
    found = _two_visits_one_day(env, T0 + 3600, COMPLETED)
    assert found["attributed_to"] == TASK + 1
    rows = found["rows"]
    assert (rows[TASK].is_duplicate, rows[TASK + 1].group_task_id) == (False, TASK)
    assert rows[TASK].site_visit_outcome == rows[TASK + 1].site_visit_outcome == "completed"


def test_decline_set_after_both_visits_makes_the_group_declined(env):
    found = _two_visits_one_day(env, T0 + 3600, DECLINED)
    assert found["attributed_to"] == TASK + 1
    rows = found["rows"]
    # Declined groups are not conducted (§2 M1); the metrics test checks M1 itself.
    assert rows[TASK].site_visit_outcome == rows[TASK + 1].site_visit_outcome == "declined"


def test_result_on_the_first_visit_only_is_the_groups(env):
    found = _two_visits_one_day(env, T0 + 300, COMPLETED)
    assert found["attributed_to"] == TASK
    rows = found["rows"]
    assert rows[TASK].site_visit_outcome == rows[TASK + 1].site_visit_outcome == "completed"


# --- Д3: the recompute script


@pytest.fixture
def engine():
    worker_engine = make_engine(os.environ["DATABASE_URL"])
    yield worker_engine
    worker_engine.dispose()


def _seed_for_script(env) -> None:
    env.amo.add_task(legacy_task())
    env.amo.add_task(legacy_task(task_id=TASK + 1, complete_till=FUNNEL_TILL + 600))
    env.amo.add_task(make_task(task_id=TASK + 2, complete_till=T0))
    env.amo.events = [status_raw("s1", LEAD, FUNNEL_TILL + 3600, (Q, 70000002))]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()


def script(env, engine, capsys, *args) -> tuple[int, dict[str, str]]:
    capsys.readouterr()
    code = recompute_main(list(args), settings=env.settings, engine=engine, now=lambda: env.now)
    lines = capsys.readouterr().out.splitlines()
    return code, dict(line.split(": ", 1) for line in lines if ": " in line and line[0].islower())


def test_script_dry_run_writes_nothing(env, engine, capsys):
    _seed_for_script(env)
    env.db.execute(update(MeasurementsVisitOutcome).values(rule_version=0))
    env.db.commit()
    before = shape(env.db)
    code, printed = script(env, engine, capsys)
    assert code == 0
    assert printed["mode"] == "dry-run"
    assert printed["stale_before"] == "3"
    assert "stale_after" not in printed
    assert shape(env.db) == before


def test_script_apply_fills_and_is_idempotent(env, engine, capsys):
    _seed_for_script(env)
    env.db.execute(update(MeasurementsVisitOutcome).values(rule_version=0))
    env.db.commit()
    env.now = NOW + timedelta(days=1)
    code, first = script(env, engine, capsys, "--apply")
    assert code == 0
    assert (first["mode"], first["stale_before"], first["stale_after"]) == ("apply", "3", "0")
    assert first["rows"] == "3"
    assert first["rows.result_source.funnel"] == "2"
    assert first["rows.result_source.site_visit"] == "1"
    assert first["rows.funnel_outcome.not_held"] == "2"
    assert first["groups.funnel.legacy.not_held"] == "1"
    assert (first["groups.with_duplicates"], first["duplicates"]) == ("1", "1")
    assert first["other_exit"] == "0"
    rows_after_first = shape(env.db)
    assert {row.computed_at for row in outcomes(env.db).values()} == {env.now}

    code, second = script(env, engine, capsys, "--apply")
    assert code == 0
    assert shape(env.db) == rows_after_first
    assert {key: value for key, value in second.items() if key != "stale_before"} == {
        key: value for key, value in first.items() if key != "stale_before"
    }
    assert second["stale_before"] == "0"


def test_script_dry_run_counts_what_apply_writes(env, engine, capsys):
    _seed_for_script(env)
    _, dry = script(env, engine, capsys)
    _, applied = script(env, engine, capsys, "--apply")
    assert {key: value for key, value in dry.items() if key != "mode"} == {
        key: value for key, value in applied.items() if key not in ("mode", "stale_after")
    }


def test_script_removes_rows_of_an_excluded_lead(env, engine, capsys):
    _seed_for_script(env)
    env.settings = MeasurementsSettings(_env_file=None, excluded_lead_ids=frozenset({LEAD}))
    code, printed = script(env, engine, capsys, "--apply")
    assert code == 0
    assert printed["leads.skipped"] == "1"
    assert outcomes(env.db) == {}
    assert attribution_count(env.db) == 0


def test_script_removes_rows_of_a_lead_it_no_longer_knows(env, engine, capsys):
    _seed_for_script(env)
    env.db.add(
        MeasurementsVisitOutcome(
            task_id=1,
            lead_id=999,
            local_date=date(2026, 10, 1),
            group_task_id=1,
            is_duplicate=False,
            result_source="funnel",
            funnel_outcome="produced",
            rule_version=OUTCOME_RULE_VERSION,
            computed_at=NOW,
        )
    )
    env.db.commit()
    code, printed = script(env, engine, capsys, "--apply")
    assert code == 0
    assert printed["leads"] == "2"
    assert 1 not in outcomes(env.db)


def test_script_reads_the_field_mapping_once_per_run(env, engine, capsys, monkeypatch):
    _seed_for_script(env)
    env.amo.add_task(legacy_task(task_id=TASK + 5, lead_id=LEAD + 1, updated_at=LATER))
    env.amo.leads[LEAD + 1] = lead_snapshot(lead_id=LEAD + 1)
    next_cycle(env)
    calls = []
    original = attribution_store.load_field_values

    def counted(db):
        calls.append(1)
        return original(db)

    monkeypatch.setattr(attribution_store, "load_field_values", counted)
    monkeypatch.setattr(recompute_module, "load_field_values", counted)
    code, printed = script(env, engine, capsys, "--apply")
    assert code == 0
    assert printed["leads"] == "2"
    assert len(calls) == 1


def test_script_waits_for_the_worker_lock(env, engine, capsys):
    _seed_for_script(env)
    env.db.execute(update(MeasurementsVisitOutcome).values(rule_version=0))
    env.db.commit()
    before = shape(env.db)
    holder = acquire_lock(engine)
    try:
        code = recompute_main(["--apply"], settings=env.settings, engine=engine)
    finally:
        release_lock(holder)
    assert code == LOCK_BUSY_EXIT
    assert "another measurements worker or backfill" in capsys.readouterr().err
    assert shape(env.db) == before


def test_script_holds_the_lock_while_it_runs(env, engine, capsys, monkeypatch):
    """The same lock as the worker: a worker started meanwhile cannot take it."""
    _seed_for_script(env)
    seen = {}
    other_process = make_engine(os.environ["DATABASE_URL"])
    original = recompute_module.compute_lead

    def compute_and_probe(*args, **kwargs):
        if not seen:
            seen["lock"] = acquire_lock(other_process)
        return original(*args, **kwargs)

    monkeypatch.setattr(recompute_module, "compute_lead", compute_and_probe)
    try:
        code, _ = script(env, engine, capsys)
    finally:
        release_lock(seen.get("lock"))
        other_process.dispose()
    assert code == 0
    assert seen["lock"] is None


# --- outcomes_stale in /measurements/status (ADR-0053 §3, item 4)


def test_status_reports_stale_outcome_rows(client, db_session, make_user, make_session):
    session, _ = db_session
    for task_id, version in ((1, OUTCOME_RULE_VERSION - 1), (2, OUTCOME_RULE_VERSION)):
        session.add(
            MeasurementsVisitOutcome(
                task_id=task_id,
                lead_id=1,
                local_date=date(2026, 10, 1),
                group_task_id=task_id,
                is_duplicate=False,
                result_source="funnel",
                funnel_outcome="produced",
                rule_version=version,
                computed_at=NOW,
            )
        )
    session.flush()
    client.cookies.set(SESSION_COOKIE, str(make_session(make_user(role="admin")).id))
    assert client.get("/measurements/status").json()["outcomes_stale"] == 1
