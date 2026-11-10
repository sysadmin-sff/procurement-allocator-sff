"""The pure attribution function: every rule and scenario of ADR-0051 §3."""

import random
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.measurements.attribution import (
    DeadlineChange,
    FieldChange,
    LeadHistory,
    VisitFacts,
    attribute,
)

NY = ZoneInfo("America/New_York")
CUTOVER = datetime(2026, 11, 9, tzinfo=NY)

NOT_SOLD = 627963
COMPLETED = 627965
SOLD = 627967
DECLINED = 627969
NEW_UNMAPPED = 999111
UNKNOWN = 555000
MAPPING = {NOT_SOLD: True, COMPLETED: True, SOLD: True, DECLINED: False, NEW_UNMAPPED: None}


def at(month, day, hour=12, minute=0, year=2027):
    return datetime(year, month, day, hour, minute, tzinfo=NY)


def visit(task_id, when):
    return VisitFacts(task_id=task_id, scheduled_at=when)


def change(event_id, when, after, before=None):
    return FieldChange(event_id=event_id, occurred_at=when, before=before, after=after)


def deadline(event_id, task_id, when, before, after):
    return DeadlineChange(
        event_id=event_id, task_id=task_id, occurred_at=when, before=before, after=after
    )


def run(visits=(), changes=(), deadlines=(), snapshot=None, snapshot_known=True):
    history = LeadHistory(
        visits=tuple(visits),
        field_changes=tuple(changes),
        deadline_changes=tuple(deadlines),
        snapshot_enum_id=snapshot,
        snapshot_known=snapshot_known,
    )
    return attribute(history, MAPPING, CUTOVER, NY)


def only(result):
    assert len(result.attributions) == 1
    return result.attributions[0]


def by_event(result):
    return {row.event_id: row for row in result.attributions}


def effective(result):
    return {row.task_id: row.event_id for row in result.attributions if row.is_effective}


# --- same_or_past


def test_same_or_past_takes_the_visit_on_the_event_day():
    row = only(run([visit(1, at(3, 10, 9))], [change("e1", at(3, 10, 15), COMPLETED)]))
    assert (row.task_id, row.rule, row.is_effective) == (1, "same_or_past", True)


def test_same_or_past_takes_the_latest_earlier_visit():
    visits = [visit(1, at(3, 10)), visit(2, at(3, 12))]
    row = only(run(visits, [change("e1", at(3, 15), COMPLETED)]))
    assert (row.task_id, row.rule) == (2, "same_or_past")


def test_same_day_takes_the_last_visit_already_due():
    visits = [visit(1, at(3, 10, 9)), visit(2, at(3, 10, 11)), visit(3, at(3, 10, 16))]
    assert only(run(visits, [change("e1", at(3, 10, 13), SOLD)])).task_id == 2


def test_same_day_with_none_due_takes_the_earliest_of_the_day():
    visits = [visit(1, at(3, 10, 14)), visit(2, at(3, 10, 16))]
    row = only(run(visits, [change("e1", at(3, 10, 9), SOLD)]))
    assert (row.task_id, row.rule) == (1, "same_or_past")


def test_a_day_boundary_uses_new_york_time():
    # 23:30 New York on 10.03 is already 11.03 in UTC.
    row = only(
        run(
            [visit(1, at(3, 10, 12)), visit(2, at(3, 11, 9))],
            [change("e1", at(3, 10, 23, 30), SOLD)],
        )
    )
    assert row.task_id == 1


# --- early_entry


def test_early_entry_takes_the_nearest_future_visit():
    visits = [visit(1, at(3, 20)), visit(2, at(3, 15))]
    row = only(run(visits, [change("e1", at(3, 10), COMPLETED)]))
    assert (row.task_id, row.rule) == (2, "early_entry")


# --- upcoming and late_decline


def test_upcoming_takes_the_nearest_visit_not_before_the_event():
    visits = [visit(1, at(3, 5)), visit(2, at(3, 15)), visit(3, at(3, 20))]
    row = only(run(visits, [change("e1", at(3, 10), DECLINED)]))
    assert (row.task_id, row.rule) == (2, "upcoming")


def test_upcoming_skips_a_visit_that_already_has_an_occurred_result():
    visits = [visit(1, at(3, 15)), visit(2, at(3, 20))]
    result = run(
        visits,
        [change("e1", at(3, 15, 18), SOLD), change("e2", at(3, 16), DECLINED, before=SOLD)],
    )
    assert by_event(result)["e2"].task_id == 2
    assert by_event(result)["e2"].rule == "upcoming"


def test_upcoming_counts_a_visit_with_only_a_decline_as_free():
    visits = [visit(1, at(3, 15))]
    result = run(
        visits,
        [change("e1", at(3, 10), DECLINED), change("e2", at(3, 11), DECLINED, before=DECLINED)],
    )
    assert by_event(result)["e2"].task_id == 1
    assert by_event(result)["e2"].rule == "upcoming"


def test_late_decline_takes_the_last_past_visit():
    visits = [visit(1, at(3, 1)), visit(2, at(3, 5))]
    row = only(run(visits, [change("e1", at(3, 10), DECLINED)]))
    assert (row.task_id, row.rule) == (2, "late_decline")


def test_late_decline_when_every_future_visit_already_occurred():
    visits = [visit(1, at(3, 15))]
    result = run(
        visits,
        [change("e1", at(3, 15, 18), SOLD), change("e2", at(3, 15, 19), DECLINED, before=SOLD)],
    )
    assert by_event(result)["e2"].rule == "late_decline"
    assert by_event(result)["e2"].task_id == 1


def test_ambiguous_decline_when_no_visit_is_past_and_every_future_one_occurred():
    """Decision 1 of the stage-5 review: not attached, counted."""
    result = run(
        [visit(1, at(3, 20))],
        [change("e1", at(3, 10), SOLD), change("e2", at(3, 11), DECLINED, before=SOLD)],
    )
    row = by_event(result)["e2"]
    assert (row.rule, row.task_id, row.deadline_source, row.is_effective) == (
        "ambiguous_decline",
        None,
        None,
        False,
    )
    assert effective(result) == {1: "e1"}


# --- cleared


def test_cleared_removes_the_result_from_the_visit_that_held_it():
    result = run(
        [visit(1, at(3, 10))],
        [change("e1", at(3, 10, 15), SOLD), change("e2", at(3, 11), None, before=SOLD)],
    )
    rows = by_event(result)
    assert (rows["e2"].rule, rows["e2"].task_id, rows["e2"].is_effective) == ("cleared", 1, False)
    assert rows["e1"].is_effective is False
    assert effective(result) == {}


def test_real_probe_sequence_ends_with_no_effective_result():
    result = run(
        [visit(1, at(3, 10))],
        [
            change("e1", at(3, 10, 13), NOT_SOLD),
            change("e2", at(3, 10, 14), SOLD, before=NOT_SOLD),
            change("e3", at(3, 10, 15), None, before=SOLD),
        ],
    )
    assert effective(result) == {}
    assert by_event(result)["e3"].task_id == 1


def test_cleared_with_nothing_held_is_recorded_without_a_visit():
    row = only(run([visit(1, at(3, 10))], [change("e1", at(3, 11), None, before=SOLD)]))
    assert (row.rule, row.task_id) == ("cleared", None)


def test_event_empty_on_both_sides_produces_nothing():
    assert run([visit(1, at(3, 10))], [change("e1", at(3, 11), None)]).attributions == ()


# --- snapshot_fallback


def test_snapshot_fallback_takes_the_last_visit_without_an_event():
    row = only(run([visit(1, at(3, 1)), visit(2, at(3, 5))], snapshot=SOLD))
    assert (row.task_id, row.rule, row.event_id) == (2, "snapshot_fallback", None)
    assert row.is_effective is True
    assert row.deadline_source == "current"


def test_no_field_data_produces_nothing():
    assert run([visit(1, at(3, 10))]).attributions == ()


def test_unknown_snapshot_produces_nothing():
    assert run([visit(1, at(3, 10))], snapshot_known=False).attributions == ()


# --- unmapped and no_visit


@pytest.mark.parametrize("enum_id", [NEW_UNMAPPED, UNKNOWN], ids=["null mapping", "unknown enum"])
def test_unmapped_event_is_not_attached(enum_id):
    row = only(run([visit(1, at(3, 10))], [change("e1", at(3, 10), enum_id)]))
    assert (row.rule, row.task_id, row.is_effective) == ("unmapped", None, False)


def test_unmapped_snapshot_is_not_attached():
    row = only(run([visit(1, at(3, 10))], snapshot=NEW_UNMAPPED))
    assert (row.rule, row.task_id, row.event_id) == ("unmapped", None, None)


def test_no_visit_when_the_lead_has_none():
    row = only(run([], [change("e1", at(3, 10), SOLD)]))
    assert (row.rule, row.task_id, row.is_effective) == ("no_visit", None, False)


def test_no_visit_for_a_snapshot_without_visits():
    row = only(run([], snapshot=SOLD))
    assert (row.rule, row.task_id, row.event_id) == ("no_visit", None, None)


def test_no_visit_when_all_visits_are_before_cutover():
    pre_cutover = visit(1, datetime(2026, 10, 1, 12, tzinfo=NY))
    row = only(run([pre_cutover], [change("e1", at(3, 10), SOLD)]))
    assert (row.rule, row.task_id) == ("no_visit", None)


def test_cutover_boundary_is_inclusive():
    row = only(run([visit(1, CUTOVER)], [change("e1", at(3, 10), SOLD)]))
    assert row.task_id == 1


# --- deadline_source


def test_deadline_from_the_last_change_before_the_event():
    # Moved 01.03 from the 5th to the 20th; a later field event sees the 20th.
    result = run(
        [visit(1, at(3, 25))],
        [change("e1", at(3, 10), DECLINED)],
        [
            deadline("d1", 1, at(3, 1), at(3, 5), at(3, 20)),
            deadline("d2", 1, at(3, 12), at(3, 20), at(3, 25)),
        ],
    )
    row = only(result)
    assert (row.rule, row.deadline_source) == ("upcoming", "history")


def test_deadline_from_value_before_of_the_first_later_change():
    result = run(
        [visit(1, at(3, 25))],
        [change("e1", at(3, 10), SOLD)],
        [deadline("d1", 1, at(3, 12), at(3, 8), at(3, 25))],
    )
    row = only(result)
    assert (row.rule, row.deadline_source) == ("same_or_past", "history")


def test_deadline_is_current_without_changes():
    row = only(run([visit(1, at(3, 5))], [change("e1", at(3, 10), SOLD)]))
    assert row.deadline_source == "current"


def test_late_decline_uses_the_historic_deadline():
    result = run(
        [visit(1, at(3, 25))],
        [change("e1", at(3, 10), DECLINED)],
        [deadline("d1", 1, at(3, 12), at(3, 8), at(3, 25))],
    )
    assert only(result).rule == "late_decline"


# --- drift


def test_drift_when_the_last_event_differs_from_the_snapshot():
    result = run([visit(1, at(3, 10))], [change("e1", at(3, 10), SOLD)], snapshot=COMPLETED)
    assert result.drift is True


def test_drift_does_not_substitute_the_snapshot_value():
    result = run([visit(1, at(3, 10))], [change("e1", at(3, 10), SOLD)], snapshot=COMPLETED)
    assert [row.rule for row in result.attributions] == ["same_or_past"]


def test_no_drift_when_they_match():
    assert not run([visit(1, at(3, 10))], [change("e1", at(3, 10), SOLD)], snapshot=SOLD).drift


def test_cleared_field_matches_an_empty_snapshot():
    changes = [change("e1", at(3, 10), SOLD), change("e2", at(3, 11), None, before=SOLD)]
    assert not run([visit(1, at(3, 10))], changes, snapshot=None).drift


def test_no_drift_before_the_first_snapshot():
    changes = [change("e1", at(3, 10), SOLD)]
    assert not run([visit(1, at(3, 10))], changes, snapshot_known=False).drift


def test_no_drift_without_events():
    assert not run([visit(1, at(3, 10))], snapshot=SOLD).drift


# --- ADR scenario table


def test_scenario_each_visit_keeps_its_own_result():
    result = run(
        [visit(1, at(3, 10)), visit(2, at(3, 20))],
        [
            change("e1", at(3, 10, 15), COMPLETED),
            change("e2", at(3, 20, 15), SOLD, before=COMPLETED),
        ],
    )
    assert effective(result) == {1: "e1", 2: "e2"}


def test_scenario_correction_stays_on_the_same_visit():
    result = run(
        [visit(1, at(3, 10))],
        [change("e1", at(3, 10, 15), COMPLETED), change("e2", at(3, 12), SOLD, before=COMPLETED)],
    )
    assert effective(result) == {1: "e2"}
    assert by_event(result)["e1"].task_id == 1
    assert by_event(result)["e1"].is_effective is False


def test_scenario_late_correction_moves_to_the_additional_visit():
    result = run(
        [visit(1, at(3, 10)), visit(2, at(3, 20))],
        [
            change("e1", at(3, 10, 15), COMPLETED),
            change("e2", at(3, 20, 15), COMPLETED, before=COMPLETED),
            change("e3", at(3, 22), SOLD, before=COMPLETED),
        ],
    )
    assert by_event(result)["e3"].task_id == 2
    assert effective(result) == {1: "e1", 2: "e3"}


def test_scenario_rescheduled_visit_keeps_an_early_decline():
    result = run(
        [visit(1, at(3, 15))],
        [change("e1", at(3, 9), DECLINED)],
        [deadline("d1", 1, at(3, 12), at(3, 10), at(3, 15))],
    )
    row = only(result)
    assert (row.task_id, row.rule, row.deadline_source) == (1, "upcoming", "history")


def test_scenario_transition_meeting_gets_a_result():
    """`kind` is not an input: only the deadline decides."""
    row = only(run([visit(1, CUTOVER)], [change("e1", at(3, 10), SOLD)]))
    assert row.rule == "same_or_past"


def test_scenario_legacy_before_cutover_gets_none():
    before_cutover = visit(1, datetime(2026, 11, 8, 23, 59, tzinfo=NY))
    row = only(run([before_cutover], [change("e1", at(3, 10), SOLD)]))
    assert row.task_id is None


# --- determinism


@pytest.mark.parametrize("seed", [1, 7, 42, 1234, 2026])
def test_result_does_not_depend_on_input_order(seed):
    visits = [visit(1, at(3, 10)), visit(2, at(3, 20)), visit(3, at(3, 12)), visit(4, at(3, 12))]
    changes = [
        change("e1", at(3, 10, 15), COMPLETED),
        change("e2", at(3, 13), DECLINED, before=COMPLETED),
        change("e3", at(3, 13), SOLD, before=DECLINED),
        change("e4", at(3, 22), None, before=SOLD),
        change("e5", at(3, 23), NOT_SOLD),
    ]
    deadlines = [
        deadline("d1", 2, at(3, 2), at(3, 18), at(3, 19)),
        deadline("d2", 2, at(3, 2), at(3, 19), at(3, 20)),
        deadline("d3", 3, at(3, 11), at(3, 9), at(3, 12)),
    ]
    expected = run(visits, changes, deadlines, snapshot=NOT_SOLD)
    shuffler = random.Random(seed)
    for _ in range(25):
        shuffler.shuffle(visits)
        shuffler.shuffle(changes)
        shuffler.shuffle(deadlines)
        assert run(visits, changes, deadlines, snapshot=NOT_SOLD) == expected


def test_events_at_the_same_moment_are_ordered_by_event_id():
    result = run(
        [visit(1, at(3, 10))],
        [
            change("b", at(3, 10, 15), SOLD, before=COMPLETED),
            change("a", at(3, 10, 15), COMPLETED),
        ],
    )
    assert effective(result) == {1: "b"}


def test_recomputing_gives_the_same_result():
    args = ([visit(1, at(3, 10))], [change("e1", at(3, 10), SOLD)])
    assert run(*args) == run(*args)
