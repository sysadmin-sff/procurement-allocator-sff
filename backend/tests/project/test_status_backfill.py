"""Verifies the backfill SQL in the ADR-0011 migration
(b15597e509ec_backfill_project_status.py) against representative rows,
including the dev-DB case documented in the ADR: a project with both
infeasible and ok AllocationRuns plus an Order, which must land on
"ordered" — not be miscategorized by the infeasible runs alone.
"""

from sqlalchemy import text


def _run_backfill(session):
    session.execute(
        text(
            """
            UPDATE projects
            SET status = 'calculated'
            WHERE status = 'draft'
              AND EXISTS (
                  SELECT 1 FROM allocation_runs
                  WHERE allocation_runs.project_id = projects.id
                    AND allocation_runs.status = 'ok'
              )
            """
        )
    )
    session.execute(
        text(
            """
            UPDATE projects
            SET status = 'ordered'
            WHERE EXISTS (
                SELECT 1 FROM orders
                WHERE orders.project_id = projects.id
            )
            """
        )
    )
    session.flush()


def test_backfill_leaves_project_with_no_runs_as_draft(db_session, make_project):
    session, *_ = db_session
    project = make_project(status="draft")

    _run_backfill(session)

    session.refresh(project)
    assert project.status == "draft"


def test_backfill_leaves_project_with_only_infeasible_runs_as_draft(
    db_session, make_project
):
    session, *_ = db_session
    from app.models import AllocationRun

    project = make_project(status="draft")
    session.add(
        AllocationRun(
            project_id=project.id,
            algorithm_version="test",
            status="infeasible",
            orphaned_materials=[],
            supplier_summaries=[],
        )
    )
    session.flush()

    _run_backfill(session)

    session.refresh(project)
    assert project.status == "draft"


def test_backfill_sets_calculated_for_project_with_ok_run_only(
    db_session, make_project
):
    session, *_ = db_session
    from app.models import AllocationRun

    project = make_project(status="draft")
    session.add(
        AllocationRun(
            project_id=project.id,
            algorithm_version="test",
            status="ok",
            orphaned_materials=[],
            supplier_summaries=[],
        )
    )
    session.flush()

    _run_backfill(session)

    session.refresh(project)
    assert project.status == "calculated"


def test_backfill_sets_ordered_for_project_with_infeasible_ok_and_order(
    db_session, make_project, make_supplier
):
    """Mirrors the real dev-DB project documented in ADR-0011 §6:
    5 infeasible runs, 26 ok runs, 3 orders -> must land on "ordered"."""
    session, *_ = db_session
    from app.models import AllocationRun, Order

    project = make_project(status="draft")
    supplier = make_supplier()
    for _ in range(5):
        session.add(
            AllocationRun(
                project_id=project.id,
                algorithm_version="test",
                status="infeasible",
                orphaned_materials=[],
                supplier_summaries=[],
            )
        )
    for _ in range(26):
        session.add(
            AllocationRun(
                project_id=project.id,
                algorithm_version="test",
                status="ok",
                orphaned_materials=[],
                supplier_summaries=[],
            )
        )
    for _ in range(3):
        session.add(
            Order(
                project_id=project.id,
                supplier_id=supplier.id,
                status="draft",
                total_amount=100.0,
                delivery_fee=0.0,
            )
        )
    session.flush()

    _run_backfill(session)

    session.refresh(project)
    assert project.status == "ordered"
