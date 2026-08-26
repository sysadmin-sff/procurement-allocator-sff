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
from app.price_ingestion.extraction import ExtractedPriceLine, PriceIngestionError
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
                page_number=1,
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


def test_upload_response_includes_suggested_sku_and_duplicate_flags(
    db_session, make_supplier
):
    """suggested_internal_sku and possible_duplicate_of are populated only
    on the upload response (transient, not persisted — see ADR-0019 §5 /
    docs/known-issues.md). This test exercises both fields together on a
    two-line batch where the lines flag each other as possible duplicates,
    proving the batch-index-to-entry-UUID translation in
    _to_import_out_with_matches actually happens, not just that the field
    exists with a default value."""
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Screen Type A", raw_sku=None, price=5.0, currency="USD",
                availability=None, min_order_qty=None,
                page_number=1,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.6,
                reasoning="no close candidate", suggested_internal_sku="SKU-A",
            ),
            embedding=[1.0] + [0.0] * 1535,
            possible_duplicate_of=[1],
        ),
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Screen Type A Variant", raw_sku=None, price=5.10, currency="USD",
                availability=None, min_order_qty=None,
                page_number=1,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.6,
                reasoning="no close candidate", suggested_internal_sku="SKU-B",
            ),
            embedding=[0.99] + [0.01] * 1535,
            possible_duplicate_of=[0],
        ),
    ]

    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        response = _upload(supplier.id)

    assert response.status_code == 201
    body = response.json()
    assert len(body["entries"]) == 2

    entry_a, entry_b = body["entries"]
    assert entry_a["suggested_internal_sku"] == "SKU-A"
    assert entry_b["suggested_internal_sku"] == "SKU-B"

    # possible_duplicate_of must be the actual persisted entry UUIDs, not
    # the raw batch indices [1]/[0] that MatchedLine carries internally.
    assert entry_a["possible_duplicate_of"] == [entry_b["id"]]
    assert entry_b["possible_duplicate_of"] == [entry_a["id"]]


def test_get_after_upload_returns_same_suggested_sku_and_duplicates_as_upload(
    db_session, make_supplier
):
    """ADR-0020: suggested_internal_sku/possible_duplicate_of are persisted
    on PriceListEntry, not just returned transiently in the upload
    response — a GET after the initial upload (e.g. after a page reload
    mid-review) must return the exact same values, not null/[] as it did
    before ADR-0020 (see docs/known-issues.md, now closed by this ADR)."""
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Screen Type A", raw_sku=None, price=5.0, currency="USD",
                availability=None, min_order_qty=None,
                page_number=1,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.6,
                reasoning="no close candidate", suggested_internal_sku="SKU-A",
            ),
            embedding=[1.0] + [0.0] * 1535,
            possible_duplicate_of=[1],
        ),
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Screen Type A Variant", raw_sku=None, price=5.10, currency="USD",
                availability=None, min_order_qty=None,
                page_number=1,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.6,
                reasoning="no close candidate", suggested_internal_sku="SKU-B",
            ),
            embedding=[0.99] + [0.01] * 1535,
            possible_duplicate_of=[0],
        ),
    ]

    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(supplier.id)

    upload_body = upload_response.json()
    import_id = upload_body["import_id"]

    get_response = client.get(f"/price-list-imports/{import_id}")

    assert get_response.status_code == 200
    get_body = get_response.json()

    # Same import, same two fields — GET must not silently drop what POST
    # returned. Compare by supplier_raw_name since entry ordering isn't
    # guaranteed to match between the two responses.
    upload_by_name = {e["supplier_raw_name"]: e for e in upload_body["entries"]}
    get_by_name = {e["supplier_raw_name"]: e for e in get_body["entries"]}

    assert set(upload_by_name) == set(get_by_name)
    for raw_name, upload_entry in upload_by_name.items():
        get_entry = get_by_name[raw_name]
        assert get_entry["suggested_internal_sku"] == upload_entry["suggested_internal_sku"]
        assert get_entry["suggested_internal_sku"] is not None
        assert set(get_entry["possible_duplicate_of"]) == set(
            upload_entry["possible_duplicate_of"]
        )
        assert get_entry["possible_duplicate_of"] != []


def test_get_import_returns_current_entries(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Screen B", raw_sku=None, price=8.0, currency="USD",
                availability=None, min_order_qty=None,
                page_number=1,
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
                page_number=1,
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
                page_number=1,
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
                page_number=1,
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


def _upload_single_entry(supplier):
    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Some Line", raw_sku=None, price=3.0, currency="USD",
                availability=None, min_order_qty=None,
                page_number=1,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.5,
                reasoning="unsure", suggested_internal_sku="SKU-X",
            ),
            embedding=[0.1] * 1536,
        )
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(supplier.id)
    return upload_response.json()


def test_apply_match_without_material_id_returns_422(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    body = _upload_single_entry(supplier)
    entry_id = body["entries"][0]["id"]

    response = client.post(
        f"/price-list-imports/{body['import_id']}/entries/{entry_id}/apply",
        json={"action": "match"},
    )

    assert response.status_code == 422


def test_apply_new_without_internal_sku_returns_422(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    body = _upload_single_entry(supplier)
    entry_id = body["entries"][0]["id"]

    response = client.post(
        f"/price-list-imports/{body['import_id']}/entries/{entry_id}/apply",
        json={"action": "new", "canonical_name": "X"},
    )

    assert response.status_code == 422


def test_apply_match_with_nonexistent_material_id_returns_404(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()
    body = _upload_single_entry(supplier)
    entry_id = body["entries"][0]["id"]

    response = client.post(
        f"/price-list-imports/{body['import_id']}/entries/{entry_id}/apply",
        json={"action": "match", "material_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404


def test_upload_response_includes_processing_status_for_failed_line(
    db_session, make_supplier
):
    """A line whose retry was exhausted during matching (ADR-0022 §2)
    still comes back as a normal PriceListEntry with
    processing_status="failed" and empty matching fields — not dropped,
    not a 5xx for the whole import."""
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    matched = [
        MatchedLine(
            extracted=ExtractedPriceLine(
                raw_name="Unmatchable Line", raw_sku=None, price=9.0, currency="USD",
                availability=None, min_order_qty=None,
                page_number=1,
            ),
            decision=MatchDecision(
                action="new", material_id=None, confidence=0.0,
                reasoning="", suggested_internal_sku=None,
            ),
            embedding=[0.1] * 1536,
            processing_status="failed",
        )
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        response = _upload(supplier.id)

    assert response.status_code == 201
    entry = response.json()["entries"][0]
    assert entry["processing_status"] == "failed"
    assert entry["matched_material_id"] is None
    assert entry["action"] is None


def test_upload_openai_failure_returns_clear_error_not_bare_500(db_session, make_supplier):
    session, _material_ids, _supplier_ids = db_session
    supplier = make_supplier()

    with patch(
        "app.price_ingestion.service.extract_price_list_lines",
        side_effect=PriceIngestionError("Не удалось связаться с сервисом распознавания."),
    ):
        response = _upload(supplier.id)

    assert response.status_code == 502
    assert response.json()["detail"]
