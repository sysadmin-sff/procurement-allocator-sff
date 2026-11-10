"""The outcome and group function against ADR-0053 §1, §3 and the §6 table.

L9, L22 and L26 (deleted, retyped, excluded and deleted leads) never reach the
pure function: the store filters them, see test_outcomes_store.py.
"""

import random
from datetime import date, datetime, timezone

import pytest

from app.measurements.outcomes import (
    OutcomeVisit,
    Pipelines,
    StatusChange,
    VisitOutcome,
    compute_outcomes,
)
from app.measurements.zone import ZONE

M, Q, SALES, OTHER = 8740486, 8740374, 8740490, 8740510
M_STAGE, M_STAGE_2, M_DELETED_STAGE = 70000001, 70000003, 77511290
Q_STAGE = 70000002
WON, LOST = 142, 143
PIPELINES = Pipelines(measurements=M, qualification=Q, sales=SALES)
N, MATT, U = 9861902, 14156562, 55555555
MEASURERS = {N: "Nazar", MATT: "Matt Measurement"}
CUTOVER = datetime(2026, 11, 9, tzinfo=ZONE)


def ny(month, day, hour=10, minute=0, second=0, year=2026) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=ZONE)


def utc(month, day, hour, minute=0, year=2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def visit(task_id, when, who=N, kind="legacy") -> OutcomeVisit:
    return OutcomeVisit(task_id=task_id, scheduled_at=when, responsible_amo_user_id=who, kind=kind)


def status(event_id, when, after, before=(M, M_STAGE)) -> StatusChange:
    return StatusChange(event_id, when, before[0], before[1], after[0], after[1])


def run(visits, changes=(), results=None, snapshot=None, **overrides):
    return compute_outcomes(
        visits,
        changes,
        overrides.get("cutover_at", CUTOVER),
        overrides.get("measurer_map", MEASURERS),
        results or {},
        PIPELINES,
        snapshot,
    )


def by_task(result) -> dict[int, VisitOutcome]:
    return {row.task_id: row for row in result.rows}


def funnel(row: VisitOutcome) -> tuple:
    return (row.result_source, row.funnel_outcome, row.no_data_reason)


# --- §6 table, one test per row


def test_l1_exit_to_m_won_is_produced():
    rows = by_task(run([visit(1, ny(9, 28, 10))], [status("e1", ny(9, 28, 18), (M, WON))]))
    assert funnel(rows[1]) == ("funnel", "produced", None)
    assert rows[1].funnel_exit_event_id == "e1"
    assert rows[1].local_date == date(2026, 9, 28)


def test_l2_q_stage_is_not_transparent_and_counts_earlier_that_day():
    rows = by_task(
        run(
            [visit(2, ny(9, 27, 16))],
            [
                status("e1", ny(9, 27, 14), (Q, Q_STAGE)),
                status("e2", ny(9, 27, 14, 0, 1), (M, M_STAGE), before=(Q, Q_STAGE)),
            ],
        )
    )
    assert funnel(rows[2]) == ("funnel", "not_held", None)
    assert rows[2].funnel_exit_event_id == "e1"


def test_l3_each_day_has_its_own_window():
    rows = by_task(
        run(
            [visit(31, ny(9, 30)), visit(32, ny(10, 1), who=MATT)],
            [status("e1", ny(9, 30, 15), (Q, Q_STAGE)), status("e2", ny(10, 3), (M, LOST))],
        )
    )
    assert funnel(rows[31]) == ("funnel", "not_held", None)
    assert funnel(rows[32]) == ("funnel", "closed", None)
    assert rows[32].measurer_key == "Matt Measurement"


def test_l4_day_near_midnight_is_the_new_york_day():
    rows = by_task(
        run(
            [visit(4, utc(11, 1, 3, 30), who=MATT)],
            [
                status("e1", ny(11, 2, 9), (M, WON)),
                status("e2", ny(11, 2, 9, 5), (SALES, 1), before=(M, WON)),
            ],
        )
    )
    assert rows[4].local_date == date(2026, 10, 31)
    assert funnel(rows[4]) == ("funnel", "produced", None)


def test_l5_no_events_means_never_in_measurements_on_the_dst_day():
    rows = by_task(run([visit(5, utc(11, 1, 6, 30))]))
    assert rows[5].local_date == date(2026, 11, 1)
    assert funnel(rows[5]) == ("funnel", "no_data", "never_in_measurements")


def test_l6_exit_before_the_visit_day_is_outside_the_window():
    rows = by_task(run([visit(6, ny(10, 15))], [status("e1", ny(10, 14), (M, WON))]))
    assert funnel(rows[6]) == ("funnel", "no_data", "window")
    assert rows[6].funnel_exit_event_id is None


def test_l7_same_day_same_measurer_is_one_group():
    rows = by_task(
        run(
            [visit(72, ny(10, 20, 14)), visit(71, ny(10, 20, 10))],
            [status("e1", ny(10, 20, 16), (M, WON))],
        )
    )
    assert (rows[71].group_task_id, rows[71].is_duplicate) == (71, False)
    assert (rows[72].group_task_id, rows[72].is_duplicate) == (71, True)
    assert funnel(rows[71]) == funnel(rows[72]) == ("funnel", "produced", None)


def test_l8_no_events_is_no_data():
    rows = by_task(run([visit(8, ny(10, 21))]))
    assert rows[8].funnel_outcome == "no_data"


def test_l10_only_the_current_deadline_counts():
    rows = by_task(run([visit(10, ny(10, 5), who=MATT)], [status("e1", ny(10, 5, 12), (M, WON))]))
    assert rows[10].local_date == date(2026, 10, 5)
    assert funnel(rows[10]) == ("funnel", "produced", None)


def test_l11_legacy_after_cutover_uses_site_visit_without_result():
    rows = by_task(run([visit(11, ny(11, 10))], [status("e1", ny(11, 10, 12), (M, WON))]))
    assert rows[11].result_source == "site_visit"
    assert (rows[11].funnel_outcome, rows[11].no_data_reason) == (None, None)
    assert rows[11].site_visit_outcome is None


def test_l12_to_l14_effective_results_are_copied():
    rows = by_task(
        run(
            [
                visit(12, ny(11, 10), kind="primary"),
                visit(13, ny(11, 11), who=MATT, kind="primary"),
                visit(14, ny(11, 12), who=MATT, kind="additional"),
            ],
            results={12: "declined", 13: "completed", 14: "sold"},
        )
    )
    assert [rows[task].site_visit_outcome for task in (12, 13, 14)] == [
        "declined",
        "completed",
        "sold",
    ]
    assert {rows[task].result_source for task in (12, 13, 14)} == {"site_visit"}


def test_l15_responsible_outside_the_map_has_a_null_key():
    rows = by_task(run([visit(15, ny(11, 12), who=U, kind="primary")]))
    assert rows[15].measurer_key is None
    assert rows[15].result_source == "site_visit"


def test_l16_future_visit_gets_a_row():
    rows = by_task(run([visit(16, ny(11, 20), kind="primary")]))
    assert (rows[16].result_source, rows[16].site_visit_outcome) == ("site_visit", None)


def test_l17_all_day_belongs_to_its_day():
    rows = by_task(
        run([visit(17, ny(11, 13, 23, 59), who=MATT, kind="primary")], results={17: "completed"})
    )
    assert rows[17].local_date == date(2026, 11, 13)
    assert rows[17].site_visit_outcome == "completed"


def test_l18_spring_forward_evening_stays_on_its_day():
    rows = by_task(run([visit(18, utc(3, 9, 3, 30))], [status("e1", ny(3, 9, 12), (M, WON))]))
    assert rows[18].local_date == date(2026, 3, 8)
    assert funnel(rows[18]) == ("funnel", "produced", None)


def test_l19_move_to_the_deleted_stage_is_not_an_exit():
    rows = by_task(
        run(
            [visit(19, ny(10, 7))],
            [
                status("e1", ny(10, 7, 12), (M, M_DELETED_STAGE)),
                status("e2", ny(10, 8), (M, LOST), before=(M, M_DELETED_STAGE)),
            ],
        )
    )
    assert funnel(rows[19]) == ("funnel", "closed", None)
    assert rows[19].funnel_exit_event_id == "e2"


def test_l21_window_ends_at_the_next_visit_day():
    rows = by_task(
        run([visit(211, ny(10, 12)), visit(212, ny(10, 14))], [status("e1", ny(10, 14), (M, WON))])
    )
    assert funnel(rows[211]) == ("funnel", "no_data", "window")
    assert funnel(rows[212]) == ("funnel", "produced", None)
    assert not rows[211].is_duplicate and not rows[212].is_duplicate


def test_l23_two_measurers_same_day_are_two_groups_sharing_the_window():
    rows = by_task(
        run(
            [visit(231, ny(10, 8, 9)), visit(232, ny(10, 8, 15), who=MATT)],
            [status("e1", ny(10, 8, 16), (M, WON))],
        )
    )
    assert (rows[231].group_task_id, rows[231].is_duplicate) == (231, False)
    assert (rows[232].group_task_id, rows[232].is_duplicate) == (232, False)
    assert funnel(rows[231]) == funnel(rows[232]) == ("funnel", "produced", None)


def test_l24_q_won_with_same_day_return_is_transparent():
    rows = by_task(
        run(
            [visit(24, ny(10, 9))],
            [
                status("e1", ny(10, 9, 11), (Q, WON)),
                status("e2", ny(10, 9, 11, 0, 1), (M, M_STAGE), before=(Q, WON)),
                status("e3", ny(10, 10), (M, LOST)),
            ],
        )
    )
    assert funnel(rows[24]) == ("funnel", "closed", None)
    assert rows[24].funnel_exit_event_id == "e3"


def test_l25_q_won_with_a_later_return_is_not_held():
    rows = by_task(
        run(
            [visit(25, ny(10, 13), who=MATT)],
            [
                status("e1", ny(10, 13, 11), (Q, WON)),
                status("e2", ny(10, 16), (M, M_STAGE), before=(Q, WON)),
            ],
        )
    )
    assert funnel(rows[25]) == ("funnel", "not_held", None)
    assert rows[25].funnel_exit_event_id == "e1"


# --- further rules


def test_exit_to_another_pipeline_is_no_data_window_and_counted():
    result = run([visit(1, ny(10, 1))], [status("e1", ny(10, 1, 12), (OTHER, 1))])
    [row] = result.rows
    assert funnel(row) == ("funnel", "no_data", "window")
    assert row.funnel_exit_event_id == "e1"
    assert result.other_exit == 1


def test_known_exits_are_not_other_exits():
    result = run(
        [visit(1, ny(10, 1)), visit(2, ny(10, 2)), visit(3, ny(10, 3))],
        [
            status("e1", ny(10, 1, 12), (SALES, 1)),
            status("e2", ny(10, 2, 12), (Q, Q_STAGE)),
            status("e3", ny(10, 3, 12), (M, LOST), before=(Q, Q_STAGE)),
        ],
    )
    assert result.other_exit == 0


def test_q_won_return_from_another_day_does_not_make_an_earlier_exit_transparent():
    rows = by_task(
        run(
            [visit(1, ny(10, 9))],
            [
                status("e1", ny(10, 9, 23, 59), (Q, WON)),
                status("e2", ny(10, 10, 0, 1), (M, M_STAGE), before=(Q, WON)),
            ],
        )
    )
    assert rows[1].funnel_outcome == "not_held"


def test_entry_into_m_that_is_not_after_the_exit_does_not_make_it_transparent():
    rows = by_task(
        run(
            [visit(1, ny(10, 9))],
            [
                status("e0", ny(10, 9, 8), (M, M_STAGE), before=(Q, Q_STAGE)),
                status("e1", ny(10, 9, 11), (Q, WON)),
            ],
        )
    )
    assert rows[1].funnel_outcome == "not_held"


def test_moves_between_measurements_stages_are_not_exits():
    rows = by_task(run([visit(1, ny(10, 9))], [status("e1", ny(10, 9, 12), (M, M_STAGE_2))]))
    assert funnel(rows[1]) == ("funnel", "no_data", "window")


def test_snapshot_in_measurements_means_the_lead_was_there():
    rows = by_task(run([visit(1, ny(10, 9))], snapshot=M))
    assert funnel(rows[1]) == ("funnel", "no_data", "window")


def test_group_outcome_is_the_first_visits_result():
    rows = by_task(
        run(
            [visit(2, ny(11, 11, 15)), visit(1, ny(11, 11, 9))],
            results={1: "completed", 2: "declined"},
        )
    )
    assert rows[1].site_visit_outcome == rows[2].site_visit_outcome == "completed"
    assert (rows[2].group_task_id, rows[2].is_duplicate) == (1, True)


def test_first_of_a_group_ties_on_task_id():
    rows = by_task(run([visit(9, ny(10, 20, 10)), visit(8, ny(10, 20, 10))]))
    assert (rows[8].is_duplicate, rows[9].is_duplicate) == (False, True)
    assert rows[9].group_task_id == 8


def test_null_measurer_key_is_a_group_key_of_its_own():
    rows = by_task(
        run(
            [
                visit(1, ny(11, 12, 9), who=U),
                visit(2, ny(11, 12, 10), who=U + 1),
                visit(3, ny(11, 12, 11)),
            ]
        )
    )
    assert rows[2].group_task_id == 1 and rows[2].is_duplicate
    assert rows[3].group_task_id == 3 and not rows[3].is_duplicate


def test_moving_a_visit_across_the_cutover_changes_the_rule_set():
    rows = by_task(run([visit(1, ny(11, 9, 0, 0))], [status("e1", ny(11, 9, 12), (M, WON))]))
    assert rows[1].result_source == "site_visit"
    rows = by_task(run([visit(1, ny(11, 8, 23, 59))], [status("e1", ny(11, 9, 12), (M, WON))]))
    assert funnel(rows[1]) == ("funnel", "produced", None)


def test_primary_before_the_cutover_uses_the_funnel():
    rows = by_task(
        run([visit(1, ny(11, 8), kind="primary")], [status("e1", ny(11, 8, 12), (M, WON))])
    )
    assert funnel(rows[1]) == ("funnel", "produced", None)


def test_measurer_map_change_applies_to_the_key():
    assert run([visit(1, ny(11, 12), who=U)]).rows[0].measurer_key is None
    changed = {**MEASURERS, U: "Newcomer"}
    assert run([visit(1, ny(11, 12), who=U)], measurer_map=changed).rows[0].measurer_key == (
        "Newcomer"
    )


def test_no_visits_gives_no_rows():
    assert run([], [status("e1", ny(10, 1), (M, WON))]).rows == ()


# --- determinism


def _rich_lead():
    visits = [
        visit(1, ny(10, 7, 9)),
        visit(2, ny(10, 7, 9)),
        visit(3, ny(10, 7, 15), who=MATT),
        visit(4, ny(10, 9)),
        visit(5, ny(10, 12)),
        visit(6, ny(11, 10), who=U),
        visit(7, ny(11, 10, 12), who=U),
    ]
    changes = [
        status("a", ny(10, 7, 12), (M, M_DELETED_STAGE)),
        status("b", ny(10, 9, 11), (Q, WON), before=(M, M_DELETED_STAGE)),
        status("c", ny(10, 9, 11, 0, 1), (M, M_STAGE), before=(Q, WON)),
        status("d", ny(10, 9, 11, 0, 1), (Q, Q_STAGE)),
        status("e", ny(10, 12, 9), (M, M_STAGE), before=(Q, Q_STAGE)),
        status("f", ny(10, 12, 18), (SALES, 1)),
    ]
    return visits, changes, {6: "completed", 7: "declined"}


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5, 6, 7])
def test_shuffled_input_gives_the_same_result(seed):
    visits, changes, results = _rich_lead()
    expected = run(visits, changes, results)
    rng = random.Random(seed)
    rng.shuffle(visits)
    rng.shuffle(changes)
    assert run(visits, changes, results) == expected


def test_rich_lead_expected_rows():
    rows = by_task(run(*_rich_lead()[:2], results=_rich_lead()[2]))
    assert [funnel(rows[task]) for task in (1, 2, 3, 4, 5)] == [
        ("funnel", "no_data", "window"),
        ("funnel", "no_data", "window"),
        ("funnel", "no_data", "window"),
        # "d" sorts after "c" on the same second: c re-enters, then d exits to Q.
        ("funnel", "not_held", None),
        ("funnel", "produced", None),
    ]
    assert rows[4].funnel_exit_event_id == "d"
    assert [rows[task].is_duplicate for task in range(1, 8)] == [
        False,
        True,
        False,
        False,
        False,
        False,
        True,
    ]
    assert rows[7].site_visit_outcome == "completed"
