"""Динамика цен по поставщикам и месяцам (ADR-0057).

Расчёт идёт по всей БД, поэтому тесты смотрят на серии своих поставщиков,
а не на общую линию «в среднем по всем» (кроме одного теста, который
проверяет формулу через свои пары)."""

import datetime
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.price_matrix import price_dynamics

CSRF = "test-csrf-token"
TODAY = datetime.date(2026, 11, 17)
SEP, OCT, NOV = datetime.date(2026, 9, 1), datetime.date(2026, 10, 1), datetime.date(2026, 11, 1)


def _series(dynamics, supplier):
    return next(s for s in dynamics.suppliers if s.supplier_id == supplier.id)


def _point(dynamics, supplier, month: str):
    return next(p for p in _series(dynamics, supplier).points if p.month == month)


def test_monthly_average_includes_unchanged_materials(
    db_session, make_material, make_supplier, make_price
):
    """Октябрь: одна позиция +10%, другая без изменений → в среднем +5%."""
    session, *_ = db_session
    supplier = make_supplier()
    m1, m2 = make_material(), make_material()
    make_price(
        m1,
        supplier,
        price=100,
        valid_from=datetime.date(2026, 8, 1),
        valid_to=datetime.date(2026, 10, 15),
    )
    make_price(m1, supplier, price=110, valid_from=datetime.date(2026, 10, 15))
    make_price(m2, supplier, price=50, valid_from=datetime.date(2026, 8, 1))

    dynamics = price_dynamics(session, start_month=SEP, end_month=NOV, today=TODAY)

    october = _point(dynamics, supplier, "2026-10")
    assert october.avg_change_pct == Decimal("5.00")
    assert (october.compared, october.up, october.down) == (2, 1, 0)
    assert _point(dynamics, supplier, "2026-09").avg_change_pct == Decimal("0.00")
    assert _point(dynamics, supplier, "2026-11").avg_change_pct == Decimal("0.00")


def test_change_on_the_first_day_belongs_to_that_month(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    supplier, material = make_supplier(), make_material()
    make_price(material, supplier, price=100, valid_from=datetime.date(2026, 8, 1), valid_to=OCT)
    make_price(material, supplier, price=90, valid_from=OCT)

    dynamics = price_dynamics(session, start_month=SEP, end_month=OCT, today=TODAY)

    assert _point(dynamics, supplier, "2026-09").avg_change_pct == Decimal("0.00")
    assert _point(dynamics, supplier, "2026-10").avg_change_pct == Decimal("-10.00")


def test_price_appeared_in_month_is_not_compared(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    supplier, material = make_supplier(), make_material()
    make_price(material, supplier, price=10, valid_from=datetime.date(2026, 10, 10))

    dynamics = price_dynamics(session, start_month=SEP, end_month=NOV, today=TODAY)

    october = _point(dynamics, supplier, "2026-10")
    assert october.avg_change_pct is None
    assert october.compared == 0
    assert _point(dynamics, supplier, "2026-11").avg_change_pct == Decimal("0.00")


def test_supplier_without_comparable_prices_has_no_series(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    supplier = make_supplier()
    make_price(make_material(), supplier, price=10, valid_from=datetime.date(2026, 11, 5))

    dynamics = price_dynamics(session, start_month=SEP, end_month=NOV, today=TODAY)

    assert all(s.supplier_id != supplier.id for s in dynamics.suppliers)


def test_current_month_is_partial_and_measured_to_today(
    db_session, make_material, make_supplier, make_price
):
    session, *_ = db_session
    supplier, material = make_supplier(), make_material()
    make_price(
        material,
        supplier,
        price=100,
        valid_from=datetime.date(2026, 8, 1),
        valid_to=datetime.date(2026, 11, 10),
    )
    make_price(material, supplier, price=120, valid_from=datetime.date(2026, 11, 10))

    dynamics = price_dynamics(session, start_month=OCT, end_month=NOV, today=TODAY)

    assert [m.month for m in dynamics.months] == ["2026-10", "2026-11"]
    assert dynamics.months[1].is_partial
    assert dynamics.months[1].end == TODAY
    assert not dynamics.months[0].is_partial
    assert dynamics.months[0].end == datetime.date(2026, 10, 31)
    assert _point(dynamics, supplier, "2026-11").avg_change_pct == Decimal("20.00")


def test_invalid_ranges_are_rejected(db_session):
    session, *_ = db_session
    with pytest.raises(ValueError):
        price_dynamics(session, start_month=NOV, end_month=OCT, today=TODAY)
    with pytest.raises(ValueError):
        price_dynamics(session, start_month=OCT, end_month=datetime.date(2026, 12, 1), today=TODAY)
    with pytest.raises(ValueError):
        price_dynamics(session, start_month=datetime.date(2023, 1, 1), end_month=NOV, today=TODAY)


def _client(make_user, make_session, role):
    user = make_user(
        email=f"{role}-dyn-{uuid.uuid4().hex[:8]}@screen-factory-florida.com", role=role
    )
    client = TestClient(app)
    client.cookies.set("session_id", str(make_session(user, csrf_token=CSRF).id))
    return client


def test_dynamics_endpoint(db_session, make_user, make_session):
    admin = _client(make_user, make_session, "admin")
    assert _client(make_user, make_session, "employee").get("/prices/dynamics").status_code == 403

    default = admin.get("/prices/dynamics")
    assert default.status_code == 200, default.text
    assert len(default.json()["months"]) == 12
    assert default.json()["months"][-1]["is_partial"] is True

    body = admin.get("/prices/dynamics", params={"start": "2026-01", "end": "2026-03"}).json()
    assert [m["month"] for m in body["months"]] == ["2026-01", "2026-02", "2026-03"]
    assert len(body["overall"]) == 3

    assert admin.get("/prices/dynamics", params={"start": "2026-13"}).status_code == 422
    assert admin.get("/prices/dynamics", params={"start": "abc"}).status_code == 422
    assert (
        admin.get("/prices/dynamics", params={"start": "2026-05", "end": "2026-02"}).status_code
        == 422
    )
