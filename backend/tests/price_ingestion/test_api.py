"""Tests for the price-list-import endpoints — see ADR-0019 §5.

The extraction + matching pipeline is always mocked at the service
boundary (match_price_list_lines) — these tests exercise routing, status
codes, and the transition to PriceListImport.status="approved", not model
accuracy (see docs/known-issues.md for that open item).
"""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import PriceListImport
from app.price_ingestion.extraction import ExtractedPriceLine
from app.price_ingestion.matching import MatchDecision, MatchedLine

client = TestClient(app)

FAKE_PDF_BYTES = b"%PDF-1.4 fake price list"


def _upload(supplier_id, content_type="application/pdf", data=FAKE_PDF_BYTES):
    return client.post(
        f"/suppliers/{supplier_id}/price-lists",
        files={"file": ("pricelist.pdf", data, content_type)},
    )


def _mock_pipeline(matched_lines):
    return patch(
        "app.price_ingestion.service.match_price_list_lines", return_value=matched_lines
    ), patch(
        "app.price_ingestion.service.extract_price_list_lines",
        return_value=[m.extracted for m in matched_lines],
    )


def test_upload_creates_import_and_entries(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Screen A", raw_sku=None, price=5.0, currency="USD",
                availability=None, min_order_qty=None,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.7,
                reasoning="no candidate close enough", suggested_internal_sku="SKU-A",
            ),
            embedding=[0.1] * 1536,
        )
    ]

    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        response = _upload(supplier.id)

    assert response.status_code == 201
    body = response.json()
    assert "import_id" in body
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["action"] is None
    assert entry["confidence"] == 0.7
    assert entry["suggested_internal_sku"] == "SKU-A"

    price_list_import = session.get(PriceListImport, uuid.UUID(body["import_id"]))
    assert price_list_import.status == "pending_review"


def test_get_import_returns_current_entries(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Screen B", raw_sku=None, price=8.0, currency="USD",
                availability=None, min_order_qty=None,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.6,
                reasoning="no match", suggested_internal_sku="SKU-B",
            ),
            embedding=[0.1] * 1536,
        )
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(supplier.id)
    import_id = upload_response.json()["import_id"]

    response = client.get(f"/price-list-imports/{import_id}")

    assert response.status_code == 200
    assert len(response.json()["entries"]) == 1


def test_apply_match_entry_updates_status_when_all_entries_resolved(
    db_session, make_supplier, make_material
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    material = make_material()

    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Known Screen", raw_sku=None, price=4.0, currency="USD",
                availability=None, min_order_qty=None,
            ),
            decision=MatchDecision(
                action="match", material_id=material.id, confidence=0.95,
                reasoning="matches", suggested_internal_sku=None,
            ),
            embedding=[0.1] * 1536,
        )
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(supplier.id)
    body = upload_response.json()
    import_id = body["import_id"]
    entry_id = body["entries"][0]["id"]

    response = client.post(
        f"/price-list-imports/{import_id}/entries/{entry_id}/apply",
        json={"action": "match", "material_id": str(material.id)},
    )

    assert response.status_code == 200

    session.expire_all()
    price_list_import = session.get(PriceListImport, uuid.UUID(import_id))
    assert price_list_import.status == "approved"


def test_apply_skip_leaves_import_pending_until_all_entries_resolved(
    db_session, make_supplier
):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Line 1", raw_sku=None, price=1.0, currency="USD",
                availability=None, min_order_qty=None,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.5,
                reasoning="unsure", suggested_internal_sku="SKU-1",
            ),
            embedding=[0.1] * 1536,
        ),
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Line 2", raw_sku=None, price=2.0, currency="USD",
                availability=None, min_order_qty=None,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.5,
                reasoning="unsure", suggested_internal_sku="SKU-2",
            ),
            embedding=[0.1] * 1536,
        ),
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(supplier.id)
    body = upload_response.json()
    import_id = body["import_id"]
    entry_1_id = body["entries"][0]["id"]

    response = client.post(
        f"/price-list-imports/{import_id}/entries/{entry_1_id}/apply",
        json={"action": "skip"},
    )
    assert response.status_code == 200

    session.expire_all()
    price_list_import = session.get(PriceListImport, uuid.UUID(import_id))
    assert price_list_import.status == "pending_review"


def test_upload_rejects_unsupported_content_type(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    response = _upload(supplier.id, content_type="text/plain")

    assert response.status_code == 422


def test_upload_returns_404_for_unknown_supplier():
    with patch("app.price_ingestion.service.extract_price_list_lines", return_value=[]):
        response = _upload(uuid.uuid4())

    assert response.status_code == 404


def test_apply_returns_404_for_unknown_entry(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    matched = []
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(supplier.id)
    import_id = upload_response.json()["import_id"]

    response = client.post(
        f"/price-list-imports/{import_id}/entries/{uuid.uuid4()}/apply",
        json={"action": "skip"},
    )

    assert response.status_code == 404
