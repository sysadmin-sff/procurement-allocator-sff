"""Task kind by ADR-0051 §3 and its 2026-11-10 change (legacy_meetings_until)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.measurements.classification import (
    classify_kind,
    is_post_cutover_meeting_ignored,
    is_transition_meeting,
)
from app.measurements.config import MeasurementsSettings

UNTIL = datetime(2026, 12, 1, tzinfo=timezone.utc)
BEFORE = UNTIL - timedelta(days=1)
AFTER = UNTIL + timedelta(days=1)
CUTOVER = datetime(2026, 11, 9, 5, tzinfo=timezone.utc)
NAZAR = 9861902
MATT = 14156562
OTHER = 8644141


def _settings(**overrides) -> MeasurementsSettings:
    return MeasurementsSettings(_env_file=None, **overrides)


def test_primary():
    assert classify_kind(_settings(), 4410970, OTHER, AFTER, AFTER) == "primary"


def test_additional():
    assert classify_kind(_settings(), 4410974, OTHER, AFTER, AFTER) == "additional"


def test_unrelated_type_is_not_a_visit():
    assert classify_kind(_settings(), 1, NAZAR, BEFORE, BEFORE) is None


@pytest.mark.parametrize("responsible", [NAZAR, MATT])
def test_open_transition_counts_every_meeting_of_a_measurer(responsible):
    assert classify_kind(_settings(), 2, responsible, AFTER, AFTER) == "legacy"


def test_meeting_of_anyone_else_is_never_a_visit():
    assert classify_kind(_settings(), 2, OTHER, BEFORE, BEFORE) is None


def test_new_account_in_the_map_applies_without_other_changes():
    assert classify_kind(_settings(measurer_map={OTHER: "New"}), 2, OTHER, AFTER, AFTER) == "legacy"


@pytest.mark.parametrize(
    "complete_till, created_at, expected",
    [
        pytest.param(BEFORE, AFTER, "legacy", id="scheduled before the close"),
        pytest.param(AFTER, BEFORE, "legacy", id="created before, scheduled later"),
        pytest.param(BEFORE, BEFORE, "legacy", id="both before"),
        pytest.param(AFTER, AFTER, None, id="both after"),
        pytest.param(UNTIL, UNTIL, None, id="exactly at the close is after it"),
    ],
)
def test_closed_transition(complete_till, created_at, expected):
    settings = _settings(legacy_meetings_until=UNTIL)
    assert classify_kind(settings, 2, NAZAR, complete_till, created_at) == expected


def test_meeting_after_the_close_is_counted_as_ignored():
    settings = _settings(legacy_meetings_until=UNTIL)
    assert is_post_cutover_meeting_ignored(settings, 2, NAZAR, AFTER, AFTER)


def test_meeting_before_the_close_is_not_ignored():
    settings = _settings(legacy_meetings_until=UNTIL)
    assert not is_post_cutover_meeting_ignored(settings, 2, NAZAR, BEFORE, BEFORE)


def test_meeting_of_a_non_measurer_is_not_counted_as_ignored():
    settings = _settings(legacy_meetings_until=UNTIL)
    assert not is_post_cutover_meeting_ignored(settings, 2, OTHER, AFTER, AFTER)


def test_nothing_is_ignored_while_the_transition_is_open():
    assert not is_post_cutover_meeting_ignored(_settings(), 2, NAZAR, AFTER, AFTER)


def test_transition_meeting_is_a_legacy_created_at_or_after_cutover():
    assert is_transition_meeting(_settings(), "legacy", CUTOVER)
    assert not is_transition_meeting(_settings(), "legacy", CUTOVER - timedelta(seconds=1))
    assert not is_transition_meeting(_settings(), "primary", CUTOVER)
