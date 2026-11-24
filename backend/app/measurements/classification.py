"""Which amo tasks count as visits (ADR-0051 §3, 2026-11-10 change; ADR-0061).

`created_at` is amo's task creation time, stored as `amo_created_at`, so the
result can be reproduced from our own data.
"""

from datetime import datetime

from app.measurements.config import MeasurementsSettings


def _transition_covers(
    settings: MeasurementsSettings, complete_till: datetime, created_at: datetime
) -> bool:
    """A meeting counts only if it is due before the close (ADR-0061): the
    creation time no longer keeps a later meeting set before the close."""
    del created_at  # kept in the signature: callers pass amo's task facts as is
    until = settings.legacy_meetings_until
    return until is None or complete_till < until


def classify_kind(
    settings: MeasurementsSettings,
    task_type_id: int,
    responsible_amo_user_id: int,
    complete_till: datetime,
    created_at: datetime,
) -> str | None:
    """Returns `primary`, `additional`, `legacy`, or None if the task is not a visit."""
    if task_type_id == settings.task_type_primary:
        return "primary"
    if task_type_id == settings.task_type_additional:
        return "additional"
    if (
        task_type_id == settings.task_type_legacy
        and responsible_amo_user_id in settings.measurer_map
        and _transition_covers(settings, complete_till, created_at)
    ):
        return "legacy"
    return None


def is_post_cutover_meeting_ignored(
    settings: MeasurementsSettings,
    task_type_id: int,
    responsible_amo_user_id: int,
    complete_till: datetime,
    created_at: datetime,
) -> bool:
    """A measurer's meeting due at or after the transition close (ADR-0061)."""
    return (
        task_type_id == settings.task_type_legacy
        and responsible_amo_user_id in settings.measurer_map
        and not _transition_covers(settings, complete_till, created_at)
    )


def is_transition_meeting(
    settings: MeasurementsSettings, kind: str | None, created_at: datetime
) -> bool:
    return kind == "legacy" and created_at >= settings.cutover_at
