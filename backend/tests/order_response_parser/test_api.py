"""Tests for POST /orders/{order_id}/parse-response — ADR-0018.

The OpenAI call is always mocked (patches
app.order_response_parser.client.parse_order_response_document) — no real
API calls in this suite. Covers grouping into matched/missing/extra,
confidence="low" staying in matched, empty extraction, invalid content-type
rejected before any OpenAI call, OpenAI failure surfaced as a clear error,
and that the endpoint never writes to OrderItem/PurchaseRecord.
"""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import OrderItem, PurchaseRecord
from app.order_response_parser.client import ExtractedLine, OrderResponseParsingError

CSRF = "test-csrf-token"
_employee_email_counter = [0]

FAKE_PDF_BYTES = b"%PDF-1.4 fake content for tests"


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def _employee_client(make_user, make_session):
    _employee_email_counter[0] += 1
    email = f"employee-order-response{_employee_email_counter[0]}@screen-factory-florida.com"
    employee = make_user(email=email, role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    return _client_as(employee_session)


def _upload(
    client,
    order_id,
    content_type="application/pdf",
    filename="response.pdf",
    data=FAKE_PDF_BYTES,
):
    return client.post(
        f"/orders/{order_id}/parse-response",
        files={"file": (filename, data, content_type)},
        headers={"X-CSRF-Token": CSRF},
    )


def _mock_extraction(lines):
    return patch(
        "app.order_response_parser.service.parse_order_response_document",
        return_value=lines,
    )


def test_full_match_all_items_found_missing_empty(
    db_session, make_supplier, make_material, make_order, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material_a = make_material(canonical_name="84 in. 18x14 Fiberglass Screen")
    material_b = make_material(canonical_name="Aluminum Frame Track")
    order = make_order(
        supplier,
        [(material_a, 10, 5.00), (material_b, 5, 12.00)],
    )
    item_a, item_b = order.items
    client = _employee_client(make_user, make_session)

    lines = [
        ExtractedLine(
            raw_description='84" PREMIER SCREEN 18/14"',
            matched_order_item_id=item_a.id,
            price=5.10,
            quantity=10,
            confidence="high",
            reasoning="matches by dimensions",
        ),
        ExtractedLine(
            raw_description="Aluminum Track",
            matched_order_item_id=item_b.id,
            price=12.00,
            quantity=5,
            confidence="high",
            reasoning="matches by name",
        ),
    ]

    with _mock_extraction(lines):
        response = _upload(client, order.id)

    assert response.status_code == 200
    body = response.json()
    assert len(body["matched"]) == 2
    assert body["missing"] == []
    assert body["extra"] == []
    matched_ids = {m["order_item_id"] for m in body["matched"]}
    assert matched_ids == {str(item_a.id), str(item_b.id)}


def test_partial_match_splits_into_all_three_categories(
    db_session, make_supplier, make_material, make_order, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material_a = make_material(canonical_name="Material A")
    material_b = make_material(canonical_name="Material B")
    order = make_order(
        supplier,
        [(material_a, 10, 5.00), (material_b, 5, 12.00)],
    )
    item_a, item_b = order.items
    client = _employee_client(make_user, make_session)

    lines = [
        ExtractedLine(
            raw_description="Material A response",
            matched_order_item_id=item_a.id,
            price=5.00,
            quantity=10,
            confidence="high",
            reasoning="exact match",
        ),
        ExtractedLine(
            raw_description="Unplanned extra item",
            matched_order_item_id=None,
            price=3.50,
            quantity=2,
            confidence="medium",
            reasoning="no corresponding order item",
        ),
    ]

    with _mock_extraction(lines):
        response = _upload(client, order.id)

    assert response.status_code == 200
    body = response.json()

    assert len(body["matched"]) == 1
    assert body["matched"][0]["order_item_id"] == str(item_a.id)

    assert len(body["missing"]) == 1
    assert body["missing"][0]["order_item_id"] == str(item_b.id)
    assert body["missing"][0]["canonical_name"] == "Material B"

    assert len(body["extra"]) == 1
    assert body["extra"][0]["raw_description"] == "Unplanned extra item"


def test_low_confidence_stays_in_matched_not_dropped_or_separated(
    db_session, make_supplier, make_material, make_order, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material()
    order = make_order(supplier, [(material, 10, 5.00)])
    item = order.items[0]
    client = _employee_client(make_user, make_session)

    lines = [
        ExtractedLine(
            raw_description="ambiguous line",
            matched_order_item_id=item.id,
            price=5.00,
            quantity=10,
            confidence="low",
            reasoning="weak textual overlap",
        ),
    ]

    with _mock_extraction(lines):
        response = _upload(client, order.id)

    assert response.status_code == 200
    body = response.json()
    assert len(body["matched"]) == 1
    assert body["matched"][0]["confidence"] == "low"
    assert body["missing"] == []
    assert body["extra"] == []


def test_empty_extraction_puts_everything_in_missing_not_an_error(
    db_session, make_supplier, make_material, make_order, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material_a = make_material()
    material_b = make_material()
    order = make_order(supplier, [(material_a, 10, 5.00), (material_b, 3, 7.00)])
    client = _employee_client(make_user, make_session)

    with _mock_extraction([]):
        response = _upload(client, order.id)

    assert response.status_code == 200
    body = response.json()
    assert body["matched"] == []
    assert body["extra"] == []
    assert len(body["missing"]) == 2


def test_invalid_content_type_rejected_before_openai_call(
    db_session, make_supplier, make_material, make_order, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material()
    order = make_order(supplier, [(material, 10, 5.00)])
    client = _employee_client(make_user, make_session)

    with patch(
        "app.order_response_parser.service.parse_order_response_document"
    ) as mock_call:
        response = _upload(
            client, order.id, content_type="text/plain", filename="notes.txt", data=b"hello"
        )

    assert response.status_code == 422
    mock_call.assert_not_called()


def test_openai_failure_returns_clear_error_not_bare_500(
    db_session, make_supplier, make_material, make_order, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material = make_material()
    order = make_order(supplier, [(material, 10, 5.00)])
    client = _employee_client(make_user, make_session)

    with patch(
        "app.order_response_parser.service.parse_order_response_document",
        side_effect=OrderResponseParsingError("Не удалось связаться с сервисом распознавания."),
    ):
        response = _upload(client, order.id)

    assert response.status_code == 502
    assert response.json()["detail"]


def test_order_not_found_returns_404(db_session, make_user, make_session):
    client = _employee_client(make_user, make_session)
    with _mock_extraction([]):
        response = _upload(client, uuid.uuid4())
    assert response.status_code == 404


def test_endpoint_does_not_write_to_order_item_or_purchase_record(
    db_session, make_supplier, make_material, make_order, make_user, make_session
):
    session, *_ = db_session
    supplier = make_supplier()
    material_a = make_material()
    material_b = make_material()
    order = make_order(supplier, [(material_a, 10, 5.00), (material_b, 5, 12.00)])
    item_a, item_b = order.items
    client = _employee_client(make_user, make_session)

    before_item_a_confirmed = item_a.confirmed_price
    before_item_a_received = item_a.received_price
    before_purchase_record_count = session.query(PurchaseRecord).count()

    lines = [
        ExtractedLine(
            raw_description="Material A response",
            matched_order_item_id=item_a.id,
            price=5.10,
            quantity=10,
            confidence="high",
            reasoning="match",
        ),
        ExtractedLine(
            raw_description="Extra unplanned line",
            matched_order_item_id=None,
            price=9.99,
            quantity=1,
            confidence="medium",
            reasoning="no match",
        ),
    ]

    with _mock_extraction(lines):
        response = _upload(client, order.id)

    assert response.status_code == 200

    session.expire_all()
    refreshed_a = session.get(OrderItem, item_a.id)
    refreshed_b = session.get(OrderItem, item_b.id)

    assert refreshed_a.confirmed_price == before_item_a_confirmed
    assert refreshed_a.received_price == before_item_a_received
    assert refreshed_a.quoted_price == item_a.quoted_price
    assert refreshed_b.confirmed_price is None
    assert refreshed_b.received_price is None

    assert session.query(PurchaseRecord).count() == before_purchase_record_count


def test_parse_response_no_session_returns_401():
    client = TestClient(app)
    response = client.post(
        f"/orders/{uuid.uuid4()}/parse-response",
        files={"file": ("response.pdf", FAKE_PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 401
