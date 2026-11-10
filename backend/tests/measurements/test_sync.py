"""Ingestion against a fake amo (ADR-0051 §3, §4); real test database."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.database import SessionLocal
from app.measurements.amo_client import AmoAuthError, AmoClient
from app.measurements.config import MeasurementsSettings
from app.measurements.models import (
    MeasurementsAmoEvent,
    MeasurementsAmoUser,
    MeasurementsFieldValue,
    MeasurementsLead,
    MeasurementsPipelineStatus,
    MeasurementsSyncState,
    MeasurementsVisit,
)
from app.measurements.sync import SyncContext, run_cycle, run_reference_cycle
from tests.measurements.amo_fixtures import (
    BASE_URL,
    TOKEN,
    deadline_event,
    field_event,
    load,
    rows,
    task,
)
from tests.measurements.fake_amo import FakeAmo

NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
CUTOVER_TS = int(datetime(2026, 11, 9, 5, tzinfo=timezone.utc).timestamp())
T0 = CUTOVER_TS + 3600
PRIMARY, ADDITIONAL, LEGACY = 4410970, 4410974, 2
NAZAR = 9861902
OTHER_USER = 8644141
LEAD = 777001
TASK = 888001


def make_task(task_id=TASK, lead_id=LEAD, task_type=PRIMARY, **overrides) -> dict:
    defaults = {
        "id": task_id,
        "entity_id": lead_id,
        "task_type_id": task_type,
        "responsible_user_id": NAZAR,
        "complete_till": T0 + 86400,
        "created_at": T0,
        "updated_at": T0,
        "duration": 3600,
    }
    return task(**{**defaults, **overrides})


def status_event(event_id, lead_id, created_at) -> dict:
    return {
        **rows("events_lead_status_changed.json", "events")[0],
        "id": event_id,
        "entity_id": lead_id,
        "created_at": created_at,
    }


def task_event(fixture, event_id, task_id, created_at, **overrides) -> dict:
    return {
        **rows(fixture, "events")[0],
        "id": event_id,
        "entity_id": task_id,
        "created_at": created_at,
        **overrides,
    }


def type_changed(event_id, task_id, created_at, new_type) -> dict:
    return task_event(
        "events_task_type_changed.json",
        event_id,
        task_id,
        created_at,
        value_before=[{"task_type": {"id": 1}}],
        value_after=[{"task_type": {"id": new_type}}],
    )


def lead_snapshot(lead_id=LEAD, updated_at=T0, **overrides) -> dict:
    return {
        **rows("leads.json", "leads")[0],
        "id": lead_id,
        "pipeline_id": 8740486,
        "status_id": 142,
        "updated_at": updated_at,
        **overrides,
    }


class Env:
    def __init__(self, db):
        self.db = db
        self.amo = FakeAmo()
        self.now = NOW
        self.settings = MeasurementsSettings(_env_file=None)
        self.client = AmoClient(
            BASE_URL,
            SecretStr(TOKEN),
            transport=self.amo.transport(),
            sleep=lambda seconds: None,
        )

    @property
    def ctx(self) -> SyncContext:
        return SyncContext(
            db=self.db, client=self.client, settings=self.settings, now=lambda: self.now
        )

    def cycle(self) -> None:
        run_cycle(self.ctx)
        self.db.expire_all()

    def visit(self, task_id=TASK) -> MeasurementsVisit | None:
        self.db.expire_all()
        return self.db.get(MeasurementsVisit, task_id)

    def lead(self, lead_id=LEAD) -> MeasurementsLead | None:
        self.db.expire_all()
        return self.db.get(MeasurementsLead, lead_id)

    def event_ids(self) -> set[str]:
        return set(self.db.scalars(select(MeasurementsAmoEvent.event_id)).all())

    def state(self, stream: str) -> MeasurementsSyncState:
        self.db.expire_all()
        return self.db.get(MeasurementsSyncState, stream)


@pytest.fixture
def env(sync_tables_clean):
    with SessionLocal() as db:
        yield Env(db)


# --- tasks


def test_task_with_empty_result_is_stored(env):
    env.amo.add_task(make_task())
    env.cycle()
    visit = env.visit()
    assert visit.lead_id == LEAD
    assert visit.kind == "primary"
    assert visit.responsible_amo_user_id == NAZAR
    assert visit.scheduled_at == datetime.fromtimestamp(T0 + 86400, timezone.utc)
    assert visit.amo_created_at == datetime.fromtimestamp(T0, timezone.utc)
    assert visit.result_text is None
    assert visit.deleted_at is None


def test_real_result_object_is_stored(env):
    real = load("task_with_result.json")
    env.amo.add_task({**real, "task_type_id": ADDITIONAL, "updated_at": T0})
    env.cycle()
    assert env.visit(real["id"]).result_text == "Synthetic result text"
    assert env.visit(real["id"]).kind == "additional"


def test_task_text_is_never_stored(env):
    env.amo.add_task(make_task(text="SECRET GATE CODE"))
    env.cycle()
    assert "SECRET GATE CODE" not in repr(vars(env.visit()))
    assert not hasattr(MeasurementsVisit, "text")


def test_all_day_is_2359_new_york_with_zero_duration(env):
    # 2026-11-12 23:59 New York (EST, UTC-5)
    till = int(datetime(2026, 11, 13, 4, 59, tzinfo=timezone.utc).timestamp())
    env.amo.add_task({**make_task(), "complete_till": till, "duration": 0})
    env.cycle()
    assert env.visit().is_all_day is True


def test_2359_with_duration_is_not_all_day(env):
    till = int(datetime(2026, 11, 13, 4, 59, tzinfo=timezone.utc).timestamp())
    env.amo.add_task({**make_task(), "complete_till": till, "duration": 3600})
    env.cycle()
    assert env.visit().is_all_day is False


def test_task_on_a_contact_is_discarded(env):
    env.amo.add_task({**make_task(), "entity_type": "contacts"})
    env.cycle()
    assert env.visit() is None


def test_older_payload_does_not_roll_a_task_back(env):
    env.amo.add_task({**make_task(), "updated_at": T0 + 100, "complete_till": T0 + 200})
    env.cycle()
    env.amo.add_task({**make_task(), "updated_at": T0 + 50, "complete_till": T0 + 999})
    env.now = NOW + timedelta(minutes=5)
    env.state("tasks_new").watermark_at = datetime.fromtimestamp(T0, timezone.utc)
    env.db.commit()
    env.cycle()
    assert env.visit().scheduled_at == datetime.fromtimestamp(T0 + 200, timezone.utc)


def test_meeting_of_a_measurer_is_legacy(env):
    env.amo.add_task(make_task(task_type=LEGACY))
    env.cycle()
    assert env.visit().kind == "legacy"


def test_meeting_created_after_cutover_is_counted_as_transition(env):
    env.amo.add_task(make_task(task_type=LEGACY))
    env.cycle()
    assert env.state("tasks_legacy").counters["transition_meetings_counted"] == 1


def test_meeting_of_someone_else_is_not_stored(env):
    env.amo.add_task({**make_task(task_type=LEGACY), "responsible_user_id": OTHER_USER})
    env.cycle()
    assert env.visit() is None


def test_meeting_after_the_close_is_ignored_and_counted(env):
    env.settings = MeasurementsSettings(
        _env_file=None, legacy_meetings_until=datetime.fromtimestamp(T0 - 10, timezone.utc)
    )
    env.amo.add_task(make_task(task_type=LEGACY))
    env.cycle()
    assert env.visit() is None
    assert env.state("tasks_legacy").counters["post_cutover_meeting_ignored"] == 1


def test_changing_the_responsible_of_a_legacy_task_retypes_it(env):
    env.amo.add_task(make_task(task_type=LEGACY))
    env.cycle()
    changed = {
        **make_task(task_type=LEGACY),
        "responsible_user_id": OTHER_USER,
        "updated_at": T0 + 10,
    }
    env.amo.add_task(changed)
    env.now = NOW + timedelta(minutes=5)
    env.state("tasks_legacy").watermark_at = datetime.fromtimestamp(T0, timezone.utc)
    env.db.commit()
    env.cycle()
    assert env.visit().deleted_reason == "retyped"


# --- repeated delivery and arrival order


def test_repeated_delivery_changes_nothing(env):
    env.amo.add_task(make_task())
    env.amo.events = [field_event("evt-1", LEAD, T0 + 5, None, 627965)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    before = (env.event_ids(), env.visit().amo_updated_at, env.lead().status_id)
    env.now = NOW + timedelta(minutes=1)
    env.cycle()
    assert (env.event_ids(), env.visit().amo_updated_at, env.lead().status_id) == before


def test_task_event_seen_before_its_task_is_recovered_from_history(env):
    event = deadline_event("evt-d1", TASK, T0 + 5, T0 + 100, T0 + 200)
    env.amo.events = [event]
    env.cycle()
    assert "evt-d1" not in env.event_ids()

    env.amo.add_task({**make_task(), "updated_at": NOW.timestamp().__int__()})
    env.now = NOW + timedelta(minutes=5)
    env.cycle()
    assert "evt-d1" in env.event_ids()


# --- first appearance


def test_first_appearance_of_a_lead_loads_its_history(env):
    env.amo.add_task(make_task())
    old = CUTOVER_TS - 86400
    env.amo.events = [
        status_event("evt-old-status", LEAD, old),
        field_event("evt-old-field", LEAD, old + 1, None, 627963),
        {**status_event("evt-other-lead", 999, old), "entity_id": 999},
        {
            **rows("events_lead_status_changed.json", "events")[0],
            "id": "evt-note",
            "type": "common_note_added",
            "entity_id": LEAD,
            "created_at": old,
        },
    ]
    env.cycle()
    assert {"evt-old-status", "evt-old-field"} <= env.event_ids()
    assert "evt-other-lead" not in env.event_ids()
    assert "evt-note" not in env.event_ids()


def test_first_appearance_of_a_task_loads_its_history(env):
    env.amo.add_task(make_task())
    old = CUTOVER_TS - 86400
    env.amo.events = [
        deadline_event("evt-old-deadline", TASK, old, T0, T0 + 1),
        task_event("events_task_completed.json", "evt-old-done", TASK, old + 1),
        task_event("events_task_completed.json", "evt-text", TASK, old + 2, type="task_added"),
    ]
    env.cycle()
    assert {"evt-old-deadline", "evt-old-done"} <= env.event_ids()
    assert "evt-text" not in env.event_ids()


def test_task_events_carry_the_lead_of_their_task(env):
    env.amo.add_task(make_task())
    env.amo.events = [deadline_event("evt-d1", TASK, T0 + 5, T0, T0 + 1)]
    env.cycle()
    assert env.db.get(MeasurementsAmoEvent, "evt-d1").lead_id == LEAD


def test_field_event_makes_an_unknown_lead_known(env):
    env.amo.events = [field_event("evt-1", LEAD, T0, None, 627967)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    assert "evt-1" in env.event_ids()
    assert env.lead().status_id == 142


def test_real_empty_value_after_is_kept_as_an_empty_list(env):
    real = rows("events_field_784029.json", "events")[0]
    assert real["value_after"] == []
    env.amo.events = [{**real, "created_at": T0}]
    env.cycle()
    event = env.db.get(MeasurementsAmoEvent, real["id"])
    assert event.value_after == []
    assert event.value_before[0]["custom_field_value"]["enum_id"] == 627967


def test_status_event_of_an_unknown_lead_is_not_stored(env):
    env.amo.events = [status_event("evt-s1", 123456, T0)]
    env.cycle()
    assert "evt-s1" not in env.event_ids()


def test_status_event_of_a_known_lead_is_stored(env):
    env.amo.add_task(make_task())
    env.cycle()
    env.amo.events = [status_event("evt-s1", LEAD, T0 + 10)]
    env.now = NOW + timedelta(minutes=1)
    env.state("events_lead_status").watermark_at = datetime.fromtimestamp(T0, timezone.utc)
    env.db.commit()
    env.cycle()
    assert "evt-s1" in env.event_ids()


# --- task events


def test_deleted_task_is_marked(env):
    env.amo.add_task(make_task())
    env.amo.events = [task_event("events_task_deleted.json", "evt-x", TASK, T0 + 5)]
    env.cycle()
    assert env.visit().deleted_reason == "deleted"
    assert env.visit().deleted_at == datetime.fromtimestamp(T0 + 5, timezone.utc)


def test_stale_task_row_does_not_undelete(env):
    env.amo.add_task(make_task())
    env.amo.events = [task_event("events_task_deleted.json", "evt-x", TASK, T0 + 5)]
    env.cycle()
    env.now = NOW + timedelta(minutes=1)
    env.cycle()
    assert env.visit().deleted_reason == "deleted"


def test_completed_at_comes_from_the_event(env):
    env.amo.add_task({**make_task(), "is_completed": True})
    env.amo.events = [task_event("events_task_completed.json", "evt-c", TASK, T0 + 7)]
    env.cycle()
    assert env.visit().completed_at == datetime.fromtimestamp(T0 + 7, timezone.utc)


def test_reopened_task_loses_completed_at(env):
    env.amo.add_task({**make_task(), "is_completed": True})
    env.amo.events = [task_event("events_task_completed.json", "evt-c", TASK, T0 + 7)]
    env.cycle()
    env.amo.add_task({**make_task(), "is_completed": False, "updated_at": T0 + 20})
    env.now = NOW + timedelta(minutes=5)
    env.state("tasks_new").watermark_at = datetime.fromtimestamp(T0, timezone.utc)
    env.db.commit()
    env.cycle()
    assert env.visit().completed_at is None


# --- retype


def test_retype_out_of_the_visit_types(env):
    env.amo.add_task(make_task())
    env.cycle()
    env.amo.add_task({**make_task(task_type=1), "updated_at": T0 + 50})
    env.amo.events = [type_changed("evt-t1", TASK, T0 + 50, 1)]
    env.now = NOW + timedelta(minutes=5)
    env.state("events_task_type").watermark_at = datetime.fromtimestamp(T0, timezone.utc)
    env.db.commit()
    env.cycle()
    assert env.visit().deleted_reason == "retyped"
    assert "evt-t1" in env.event_ids()


def test_retype_back_restores_the_row(env):
    test_retype_out_of_the_visit_types(env)
    env.amo.add_task({**make_task(task_type=ADDITIONAL), "updated_at": T0 + 90})
    env.amo.events.append(type_changed("evt-t2", TASK, T0 + 90, ADDITIONAL))
    env.now = NOW + timedelta(minutes=10)
    env.state("events_task_type").watermark_at = datetime.fromtimestamp(T0, timezone.utc)
    env.db.commit()
    env.cycle()
    visit = env.visit()
    assert visit.deleted_at is None
    assert visit.deleted_reason is None
    assert visit.kind == "additional"


def test_task_entering_the_visit_types_is_stored_with_history(env):
    env.amo.tasks[TASK] = {**make_task(task_type=PRIMARY), "updated_at": CUTOVER_TS - 500}
    env.amo.events = [
        deadline_event("evt-old", TASK, CUTOVER_TS - 900, T0, T0 + 1),
        type_changed("evt-in", TASK, T0, PRIMARY),
    ]
    env.settings = MeasurementsSettings(_env_file=None)
    env.cycle()
    assert env.visit().kind == "primary"
    assert {"evt-old", "evt-in"} <= env.event_ids()


def test_retype_of_an_unrelated_task_is_ignored_without_a_read(env):
    env.amo.events = [type_changed("evt-unrelated", TASK, T0, 1)]
    env.cycle()
    assert "evt-unrelated" not in env.event_ids()
    assert env.amo.calls_to(f"/tasks/{TASK}") == []


def test_retyped_redelivery_does_not_read_the_task_again(env):
    env.amo.add_task(make_task())
    env.amo.events = [type_changed("evt-t1", TASK, T0 + 1, PRIMARY)]
    env.cycle()
    calls = len(env.amo.calls_to(f"/tasks/{TASK}"))
    env.now = NOW + timedelta(minutes=1)
    env.cycle()
    assert len(env.amo.calls_to(f"/tasks/{TASK}")) == calls


# --- excluded leads


def test_excluded_lead_is_dropped_everywhere(env):
    env.settings = MeasurementsSettings(_env_file=None, excluded_lead_ids=frozenset({LEAD}))
    env.amo.add_task(make_task())
    env.amo.events = [
        field_event("evt-f", LEAD, T0, None, 627967),
        status_event("evt-s", LEAD, T0),
    ]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    assert env.visit() is None
    assert env.lead() is None
    assert env.event_ids() == set()


# --- windows and failures


def test_success_moves_the_watermark_to_the_start_of_the_window(env):
    env.amo.add_task(make_task())
    env.cycle()
    state = env.state("tasks_new")
    assert state.watermark_at == NOW
    assert state.last_status == "ok"
    assert state.last_success_at == NOW
    assert state.consecutive_failures == 0


def test_next_window_overlaps_by_two_minutes(env):
    env.cycle()
    env.now = NOW + timedelta(minutes=5)
    env.amo.requests.clear()
    env.cycle()
    sent = env.amo.calls_to("/tasks")[0].url.params["filter[updated_at][from]"]
    assert int(sent) == int(NOW.timestamp()) - 120


def test_failure_on_a_later_page_keeps_the_watermark(env):
    env.amo.page_size = 1
    env.amo.add_task(make_task(task_id=1))
    env.amo.add_task(make_task(task_id=2))

    def fail_second_page(request):
        is_second = request.url.path.endswith("/tasks") and "page=2" in str(request.url)
        return httpx.Response(500) if is_second else None

    env.amo.fail_when = fail_second_page
    env.cycle()
    state = env.state("tasks_new")
    assert state.watermark_at is None
    assert state.last_status == "error"
    assert state.last_http_status == 500
    assert state.consecutive_failures == 1

    env.amo.fail_when = None
    env.now = NOW + timedelta(minutes=5)
    env.cycle()
    assert env.visit(1) is not None and env.visit(2) is not None
    assert env.state("tasks_new").watermark_at == env.now
    assert env.state("tasks_new").consecutive_failures == 0


def test_a_failing_stream_does_not_block_the_others(env):
    env.amo.add_task(make_task(task_type=LEGACY))

    def fail_new_types(request):
        is_new = "filter%5Btask_type%5D%5B%5D=4410970" in str(request.url)
        return httpx.Response(500) if is_new else None

    env.amo.fail_when = fail_new_types
    env.cycle()
    assert env.state("tasks_new").last_status == "error"
    assert env.visit().kind == "legacy"


def test_auth_failure_is_recorded_and_stops_the_cycle(env):
    env.amo.fail_when = lambda request: httpx.Response(401)
    with pytest.raises(AmoAuthError):
        run_cycle(env.ctx)
    state = env.state("tasks_new")
    assert state.last_status == "auth_failed"
    assert state.last_http_status == 401
    assert env.state("tasks_legacy") is None


# --- lead snapshots


def test_lead_snapshot_fields(env):
    env.amo.add_task(make_task())
    env.amo.leads[LEAD] = lead_snapshot(updated_at=T0, price=12500, closed_at=T0 + 1)
    env.cycle()
    lead = env.lead()
    assert lead.pipeline_id == 8740486
    assert lead.status_id == 142
    assert lead.site_visit_enum_id == 627967
    assert lead.price == 12500
    assert lead.closed_at == datetime.fromtimestamp(T0 + 1, timezone.utc)


def test_lead_with_null_custom_fields_has_no_result(env):
    env.amo.add_task(make_task())
    env.amo.leads[LEAD] = lead_snapshot(custom_fields_values=None)
    env.cycle()
    assert env.lead().site_visit_enum_id is None
    assert env.lead().amo_updated_at is not None


def test_older_snapshot_does_not_roll_a_lead_back(env):
    env.amo.add_task(make_task())
    env.amo.leads[LEAD] = lead_snapshot(updated_at=T0 + 100, status_id=142)
    env.cycle()
    env.amo.leads[LEAD] = lead_snapshot(updated_at=T0 + 50, status_id=143)
    env.amo.add_task({**make_task(), "updated_at": T0 + 300})
    env.now = NOW + timedelta(minutes=5)
    env.cycle()
    assert env.lead().status_id == 142


def test_leads_are_read_in_batches_of_fifty(env):
    for number in range(120):
        lead_id = 500000 + number
        env.amo.add_task(make_task(task_id=600000 + number, lead_id=lead_id))
        env.amo.leads[lead_id] = lead_snapshot(lead_id=lead_id)
    env.cycle()
    sizes = [len(call.url.params.get_list("filter[id][]")) for call in env.amo.calls_to("/leads")]
    assert sizes == [50, 50, 20]
    assert env.lead(500119).status_id == 142


def test_unchanged_leads_are_not_read_again(env):
    env.amo.add_task(make_task())
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    env.amo.requests.clear()
    env.now = NOW + timedelta(hours=1)
    env.cycle()
    assert env.amo.calls_to("/leads") == []


# --- reference data


def test_reference_updates_labels_and_keeps_the_mapping(env):
    env.amo.custom_fields["_embedded"]["custom_fields"][0]["enums"][0]["value"] = "Renamed"
    run_reference_cycle(env.ctx)
    env.db.expire_all()
    row = env.db.get(MeasurementsFieldValue, 627963)
    assert row.label == "Renamed"
    assert row.sort == 500
    assert row.visit_occurred is True
    assert row.outcome_type == "not_sold"


def test_reference_adds_a_new_enum_without_mapping(env):
    enums = env.amo.custom_fields["_embedded"]["custom_fields"][0]["enums"]
    enums.append({"id": 999111, "value": "New outcome", "sort": 9})
    run_reference_cycle(env.ctx)
    env.db.expire_all()
    row = env.db.get(MeasurementsFieldValue, 999111)
    assert row.label == "New outcome"
    assert row.visit_occurred is None
    assert row.outcome_type is None


def test_reference_marks_a_removed_enum_inactive(env):
    enums = env.amo.custom_fields["_embedded"]["custom_fields"][0]["enums"]
    enums[:] = [enum for enum in enums if enum["id"] != 627969]
    run_reference_cycle(env.ctx)
    env.db.expire_all()
    row = env.db.get(MeasurementsFieldValue, 627969)
    assert row.is_active is False
    assert row.outcome_type == "declined"


def test_reference_missing_field_changes_nothing(env):
    env.amo.custom_fields["_embedded"]["custom_fields"] = []
    run_reference_cycle(env.ctx)
    env.db.expire_all()
    assert env.db.get(MeasurementsFieldValue, 627963).is_active is True
    assert env.state("reference_custom_fields").last_status == "error"


def test_reference_users(env):
    users = env.amo.users["_embedded"]["users"]
    next(user for user in users if user["id"] == 14156562)["rights"]["is_active"] = False
    run_reference_cycle(env.ctx)
    assert env.db.get(MeasurementsAmoUser, 9861902).name == "Synthetic Surveyor 1"
    assert env.db.get(MeasurementsAmoUser, 9861902).is_active is True
    assert env.db.get(MeasurementsAmoUser, 14156562).is_active is False


def test_reference_pipelines_use_a_composite_key(env):
    pipelines = {
        pipeline["id"]: pipeline for pipeline in env.amo.pipelines["_embedded"]["pipelines"]
    }
    pipelines[8740490]["is_archive"] = True
    run_reference_cycle(env.ctx)
    first = env.db.get(MeasurementsPipelineStatus, (8740486, 142))
    second = env.db.get(MeasurementsPipelineStatus, (8740490, 142))
    assert first.pipeline_name == pipelines[8740486]["name"]
    assert first.is_archived is False
    assert second.is_archived is True


def test_reference_stores_every_real_status(env):
    run_reference_cycle(env.ctx)
    expected = sum(
        len(pipeline["_embedded"]["statuses"])
        for pipeline in env.amo.pipelines["_embedded"]["pipelines"]
    )
    assert env.db.query(MeasurementsPipelineStatus).count() == expected


def test_lead_with_the_real_field_layout_but_no_site_visit_value(env):
    """The probed leads had no Site Visit Result: the field is absent, not empty."""
    real = rows("leads.json", "leads")[1]
    assert all(field["field_id"] != 784029 for field in real["custom_fields_values"])
    env.amo.add_task(make_task())
    env.amo.leads[LEAD] = {**real, "id": LEAD, "updated_at": T0}
    env.cycle()
    assert env.lead().site_visit_enum_id is None
    assert env.lead().amo_updated_at is not None


def test_module_only_issues_get_requests(env):
    env.amo.add_task(make_task())
    env.amo.events = [type_changed("evt-t1", TASK, T0 + 1, PRIMARY)]
    env.amo.leads[LEAD] = lead_snapshot()
    env.cycle()
    run_reference_cycle(env.ctx)
    assert {request.method for request in env.amo.requests} == {"GET"}


def test_transport_retries_are_counted_per_stream(env):
    env.amo.add_task(make_task())
    drops = {"left": 2}

    def drop_twice(request):
        if request.url.path.endswith("/tasks") and drops["left"]:
            drops["left"] -= 1
            raise httpx.RemoteProtocolError("dropped")
        return None

    env.amo.fail_when = drop_twice
    env.cycle()
    assert env.state("tasks_new").counters["transport_retries"] == 2
    assert env.state("tasks_legacy").counters.get("transport_retries", 0) == 0
    assert env.visit() is not None
