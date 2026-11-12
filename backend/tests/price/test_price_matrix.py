"""Матрица цен и история пары (ADR-0054).

Матрица строится по всей БД, поэтому тесты смотрят только на свои
материалы/поставщиков, а не на общие счётчики."""

import datetime
import uuid
from datetime import timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Price, PriceListImport
from app.services.price_matrix import STALE_AFTER_DAYS, build_price_matrix, price_history

CSRF = "test-csrf-token"
TODAY = datetime.date(2026, 11, 12)


def _d(days_ago: int) -> datetime.date:
    return TODAY - datetime.timedelta(days=days_ago)


def _row(matrix, material):
    return next(r for r in matrix.rows if r.material_id == material.id)


def _cell(matrix, material, supplier):
    return next(c for c in _row(matrix, material).cells if c.supplier_id == supplier.id)


def _supplier(matrix, supplier):
    return next(s for s in matrix.suppliers if s.id == supplier.id)


@pytest.fixture
def make_import(db_session):
    session, *_ = db_session
    created: list = []

    def _make(supplier):
        imp = PriceListImport(
            supplier_id=supplier.id,
            file_ref="test.pdf",
            uploaded_at=datetime.datetime(2026, 11, 1, tzinfo=timezone.utc),
            status="approved",
        )
        session.add(imp)
        session.flush()
        created.append(imp.id)
        return imp

    yield _make

    if created:
        session.rollback()
        session.query(Price).filter(Price.source_import_id.in_(created)).delete(
            synchronize_session=False
        )
        session.query(PriceListImport).filter(PriceListImport.id.in_(created)).delete(
            synchronize_session=False
        )
        session.commit()


# --- режим «предыдущая версия» ---------------------------------------------


def test_price_drop_vs_previous_version_is_down(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    material, supplier = make_material(), make_supplier()
    make_price(material, supplier, price=50, valid_from=_d(60), valid_to=_d(10))
    make_price(material, supplier, price=48, valid_from=_d(10))

    cell = _cell(build_price_matrix(session, today=TODAY), material, supplier)

    assert cell.change == "down"
    assert cell.price == Decimal("48")
    assert cell.baseline_price == Decimal("50")
    assert cell.change_pct == Decimal("-4.0")


def test_price_rise_vs_previous_version_is_up(db_session, make_material, make_supplier, make_price):
    session, *_ = db_session
    material, supplier = make_material(), make_supplier()
    make_price(material, supplier, price=1.0, valid_from=_d(30), valid_to=_d(2))
    make_price(material, supplier, price=1.7, valid_from=_d(2))

    cell = _cell(build_price_matrix(session, today=TODAY), material, supplier)

    assert cell.change == "up"
    assert cell.change_pct == Decimal("70.0")


def test_single_version_is_new_and_equal_is_same(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    material, s1, s2 = make_material(), make_supplier("A"), make_supplier("B")
    make_price(material, s1, price=10, valid_from=_d(5))
    make_price(material, s2, price=12, valid_from=_d(40), valid_to=_d(3))
    make_price(material, s2, price=12, valid_from=_d(3))

    matrix = build_price_matrix(session, today=TODAY)

    assert _cell(matrix, material, s1).change == "new"
    assert _cell(matrix, material, s1).baseline_price is None
    assert _cell(matrix, material, s2).change == "same"


def test_previous_version_is_the_latest_closed_one(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    material, supplier = make_material(), make_supplier()
    make_price(material, supplier, price=30, valid_from=_d(90), valid_to=_d(60))
    make_price(material, supplier, price=20, valid_from=_d(60), valid_to=_d(5))
    make_price(material, supplier, price=25, valid_from=_d(5))

    cell = _cell(build_price_matrix(session, today=TODAY), material, supplier)

    assert cell.baseline_price == Decimal("20")
    assert cell.change == "up"


# --- режим «на дату» --------------------------------------------------------


def test_compare_to_date_uses_price_effective_on_that_date(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    material, supplier = make_material(), make_supplier()
    make_price(material, supplier, price=30, valid_from=_d(90), valid_to=_d(60))
    make_price(material, supplier, price=20, valid_from=_d(60), valid_to=_d(5))
    make_price(material, supplier, price=25, valid_from=_d(5))

    cell = _cell(build_price_matrix(session, compare_to=_d(70), today=TODAY), material, supplier)

    assert cell.baseline_price == Decimal("30")
    assert cell.change == "down"


def test_compare_to_on_switch_day_uses_the_new_version(
    db_session, make_material, make_supplier, make_price
):
    """valid_to — день, с которого действует следующая версия, а не последний
    день действия закрытой."""
    session, *_ = db_session
    material, supplier = make_material(), make_supplier()
    make_price(material, supplier, price=30, valid_from=_d(90), valid_to=_d(60))
    make_price(material, supplier, price=20, valid_from=_d(60))

    cell = _cell(build_price_matrix(session, compare_to=_d(60), today=TODAY), material, supplier)

    assert cell.baseline_price == Decimal("20")
    assert cell.change == "same"


def test_compare_to_before_first_price_is_new(db_session, make_material, make_supplier, make_price):
    session, *_ = db_session
    material, supplier = make_material(), make_supplier()
    make_price(material, supplier, price=10, valid_from=_d(20))

    cell = _cell(build_price_matrix(session, compare_to=_d(30), today=TODAY), material, supplier)

    assert cell.change == "new"


# --- строки, ячейки, поставщики --------------------------------------------


def test_cheapest_marks_all_ties_and_needs_two_prices(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    m_multi, m_single = make_material(), make_material()
    s1, s2, s3 = make_supplier("A"), make_supplier("B"), make_supplier("C")
    make_price(m_multi, s1, price=5)
    make_price(m_multi, s2, price=5)
    make_price(m_multi, s3, price=7)
    make_price(m_single, s1, price=9)

    matrix = build_price_matrix(session, today=TODAY)

    assert _cell(matrix, m_multi, s1).is_cheapest
    assert _cell(matrix, m_multi, s2).is_cheapest
    assert not _cell(matrix, m_multi, s3).is_cheapest
    assert not _cell(matrix, m_single, s1).is_cheapest


def test_material_without_prices_is_a_row_with_no_cells(db_session, make_material):
    session, *_ = db_session
    material = make_material()

    row = _row(build_price_matrix(session, today=TODAY), material)

    assert row.cells == []


def test_closed_only_pair_has_no_cell(db_session, make_material, make_supplier, make_price):
    session, *_ = db_session
    material, supplier = make_material(), make_supplier()
    make_price(material, supplier, price=10, valid_from=_d(40), valid_to=_d(10))

    matrix = build_price_matrix(session, today=TODAY)

    assert _row(matrix, material).cells == []
    assert all(s.id != supplier.id for s in matrix.suppliers)


def test_supplier_staleness_and_change_counts(db_session, make_material, make_supplier, make_price):
    session, *_ = db_session
    m1, m2, m3 = make_material(), make_material(), make_material()
    fresh, stale = make_supplier("Fresh"), make_supplier("Stale")
    make_price(m1, fresh, price=10, valid_from=_d(50), valid_to=_d(3))
    make_price(m1, fresh, price=9, valid_from=_d(3))
    make_price(m2, fresh, price=10, valid_from=_d(50), valid_to=_d(3))
    make_price(m2, fresh, price=11, valid_from=_d(3))
    make_price(m3, fresh, price=4, valid_from=_d(1))
    make_price(m1, stale, price=12, valid_from=_d(STALE_AFTER_DAYS + 1))

    matrix = build_price_matrix(session, today=TODAY)
    f, s = _supplier(matrix, fresh), _supplier(matrix, stale)

    assert f.last_price_date == _d(1)
    assert f.days_since_update == 1
    assert not f.is_stale
    assert (f.changes.down, f.changes.up, f.changes.new) == (1, 1, 1)
    assert f.active_price_count == 3
    assert s.is_stale
    assert s.days_since_update == STALE_AFTER_DAYS + 1


def test_supplier_exactly_at_threshold_is_not_stale(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    material, supplier = make_material(), make_supplier()
    make_price(material, supplier, price=1, valid_from=_d(STALE_AFTER_DAYS))

    assert not _supplier(build_price_matrix(session, today=TODAY), supplier).is_stale


# --- история пары -----------------------------------------------------------


def test_history_newest_first_with_sources_and_changes(
    db_session, make_material, make_supplier, make_price, make_import
):
    session, *_ = db_session
    material, supplier = make_material(), make_supplier()
    imp = make_import(supplier)
    first = make_price(material, supplier, price=50, valid_from=_d(90), valid_to=_d(60))
    imported = make_price(material, supplier, price=52, valid_from=_d(60), valid_to=_d(5))
    imported.source_import_id = imp.id
    edited = make_price(material, supplier, price=48, valid_from=_d(5))
    # version_price() наследует source_import_id — ручная правка поверх импорта
    edited.source_import_id = imp.id
    session.flush()

    history = price_history(session, material_id=material.id, supplier_id=supplier.id)

    assert [h.id for h in history] == [edited.id, imported.id, first.id]
    assert [h.source for h in history] == ["manual", "import", "manual"]
    assert [h.change for h in history] == ["down", "up", None]
    assert history[1].import_id == imp.id
    assert history[1].import_uploaded_at is not None
    assert history[0].import_id is None


# --- API ---------------------------------------------------------------------


def _client(make_user, make_session, role):
    user = make_user(
        email=f"{role}-matrix-{uuid.uuid4().hex[:8]}@screen-factory-florida.com", role=role
    )
    client = TestClient(app)
    client.cookies.set("session_id", str(make_session(user, csrf_token=CSRF).id))
    return client


def test_matrix_endpoint_admin_only(db_session, make_user, make_session):
    assert _client(make_user, make_session, "employee").get("/prices/matrix").status_code == 403
    assert _client(make_user, make_session, "admin").get("/prices/matrix").status_code == 200


def test_matrix_endpoint_returns_cell_and_supplier(
    db_session, make_material, make_supplier, make_price, make_user, make_session
):
    material, supplier = make_material(), make_supplier()
    make_price(material, supplier, price=50, valid_from=_d(60), valid_to=_d(10))
    make_price(material, supplier, price=48, valid_from=_d(10))
    client = _client(make_user, make_session, "admin")

    body = client.get("/prices/matrix", params={"compare_to": str(_d(30))}).json()

    assert body["compare_to"] == str(_d(30))
    row = next(r for r in body["rows"] if r["material_id"] == str(material.id))
    cell = next(c for c in row["cells"] if c["supplier_id"] == str(supplier.id))
    assert cell["price"] == 48
    assert cell["baseline_price"] == 50
    assert cell["change"] == "down"
    assert any(s["id"] == str(supplier.id) for s in body["suppliers"])


def test_history_endpoint(
    db_session, make_material, make_supplier, make_price, make_user, make_session
):
    material, supplier = make_material(), make_supplier()
    make_price(material, supplier, price=50, valid_from=_d(60), valid_to=_d(10))
    make_price(material, supplier, price=48, valid_from=_d(10))
    client = _client(make_user, make_session, "admin")

    response = client.get(
        "/prices/history",
        params={"material_id": str(material.id), "supplier_id": str(supplier.id)},
    )

    assert response.status_code == 200
    assert [h["price"] for h in response.json()] == [48, 50]
    assert client.get("/prices/history").status_code == 422
