"""Tests for the price-list-import endpoints — see ADR-0019 §5, ADR-0025.

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

FAKE_PDF_BYTES = b"%PDF-1.4 fake price list"
CSRF = "test-csrf-token"
_admin_email_counter = [0]


def _client_as(user_session):
    client = TestClient(app)
    client.cookies.set("session_id", str(user_session.id))
    return client


def _admin_client(make_user, make_session):
    _admin_email_counter[0] += 1
    admin = make_user(
        email=f"admin-price-ingestion{_admin_email_counter[0]}@screen-factory-florida.com",
        role="admin",
    )
    admin_session = make_session(admin, csrf_token=CSRF)
    return _client_as(admin_session)


def _upload(client, supplier_id, content_type="application/pdf", data=FAKE_PDF_BYTES):
    return client.post(
        f"/suppliers/{supplier_id}/price-lists",
        files={"file": ("pricelist.pdf", data, content_type)},
        headers={"X-CSRF-Token": CSRF},
    )


def _mock_pipeline(matched_lines):
    return patch(
        "app.price_ingestion.service.match_price_list_lines", return_value=matched_lines
    ), patch(
        "app.price_ingestion.service.extract_price_list_lines",
        return_value=[m.extracted for m in matched_lines],
    )


def _extracted(raw_name="Screen A", price=5.0, page_number=1):
    return ExtractedPriceLine(
        raw_name=raw_name, raw_sku=None, price=price, currency="USD",
        availability=None, min_order_qty=None, page_number=page_number,
    )


def test_upload_creates_import_and_entries(
    db_session, make_supplier, make_material, make_user, make_session
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material = make_material()
    client = _admin_client(make_user, make_session)

    matched = [
        MatchedLine(
            extracted=_extracted(raw_name="Screen A"),
            decision=MatchDecision(
                action="match", material_id=material.id, confidence=0.85,
                reasoning="close match",
            ),
        )
    ]

    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        response = _upload(client, supplier.id)

    assert response.status_code == 201
    body = response.json()
    assert "import_id" in body
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["action"] is None
    assert entry["confidence"] == 0.85
    assert "suggested_internal_sku" not in entry

    price_list_import = session.get(PriceListImport, uuid.UUID(body["import_id"]))
    assert price_list_import.status == "pending_review"


def test_not_found_line_is_not_persisted_as_entry(
    db_session, make_supplier, make_user, make_session
):
    """ADR-0025 §5: action="not_found" lines are never created as
    PriceListEntry — not shown as skipped, not shown at all."""
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    before_count = session.query(PriceListImport).count()

    matched = [
        MatchedLine(
            extracted=_extracted(raw_name="No Match Here"),
            decision=MatchDecision(
                action="not_found", material_id=None, confidence=0.9,
                reasoning="nothing close in catalog",
            ),
        )
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        response = _upload(client, supplier.id)

    assert response.status_code == 201
    body = response.json()
    assert body["entries"] == []

    import_id = uuid.UUID(body["import_id"])
    price_list_import = session.get(PriceListImport, import_id)
    assert price_list_import is not None
    assert len(price_list_import.entries) == 0
    assert session.query(PriceListImport).count() == before_count + 1


def test_response_schema_never_includes_suggested_internal_sku(
    db_session, make_supplier, make_material, make_user, make_session
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material = make_material()
    client = _admin_client(make_user, make_session)

    matched = [
        MatchedLine(
            extracted=_extracted(raw_name="Screen A"),
            decision=MatchDecision(
                action="match", material_id=material.id, confidence=0.6,
                reasoning="uncertain match",
            ),
        )
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        response = _upload(client, supplier.id)

    body = response.json()
    for entry in body["entries"]:
        assert "suggested_internal_sku" not in entry


def test_upload_response_includes_duplicate_flags(
    db_session, make_supplier, make_material, make_user, make_session
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material_a = make_material()
    client = _admin_client(make_user, make_session)

    matched = [
        MatchedLine(
            extracted=_extracted(raw_name="Screen Type A"),
            decision=MatchDecision(
                action="match", material_id=material_a.id, confidence=0.6,
                reasoning="close candidate",
            ),
            possible_duplicate_of=[1],
        ),
        MatchedLine(
            extracted=_extracted(raw_name="Screen Type A Variant", price=5.10),
            decision=MatchDecision(
                action="match", material_id=material_a.id, confidence=0.6,
                reasoning="close candidate",
            ),
            possible_duplicate_of=[0],
        ),
    ]

    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        response = _upload(client, supplier.id)

    assert response.status_code == 201
    body = response.json()
    assert len(body["entries"]) == 2

    entry_a, entry_b = body["entries"]
    assert entry_a["possible_duplicate_of"] == [entry_b["id"]]
    assert entry_b["possible_duplicate_of"] == [entry_a["id"]]


def test_get_after_upload_returns_same_duplicates_as_upload(
    db_session, make_supplier, make_material, make_user, make_session
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material_a = make_material()
    client = _admin_client(make_user, make_session)

    matched = [
        MatchedLine(
            extracted=_extracted(raw_name="Screen Type A"),
            decision=MatchDecision(
                action="match", material_id=material_a.id, confidence=0.6,
                reasoning="close candidate",
            ),
            possible_duplicate_of=[1],
        ),
        MatchedLine(
            extracted=_extracted(raw_name="Screen Type A Variant", price=5.10),
            decision=MatchDecision(
                action="match", material_id=material_a.id, confidence=0.6,
                reasoning="close candidate",
            ),
            possible_duplicate_of=[0],
        ),
    ]

    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(client, supplier.id)

    upload_body = upload_response.json()
    import_id = upload_body["import_id"]

    get_response = client.get(f"/price-list-imports/{import_id}")

    assert get_response.status_code == 200
    get_body = get_response.json()

    upload_by_name = {e["supplier_raw_name"]: e for e in upload_body["entries"]}
    get_by_name = {e["supplier_raw_name"]: e for e in get_body["entries"]}

    assert set(upload_by_name) == set(get_by_name)
    for raw_name, upload_entry in upload_by_name.items():
        get_entry = get_by_name[raw_name]
        assert set(get_entry["possible_duplicate_of"]) == set(
            upload_entry["possible_duplicate_of"]
        )
        assert get_entry["possible_duplicate_of"] != []


def test_get_import_returns_current_entries(
    db_session, make_supplier, make_material, make_user, make_session
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material = make_material()
    client = _admin_client(make_user, make_session)

    matched = [
        MatchedLine(
            extracted=_extracted(raw_name="Screen B", price=8.0),
            decision=MatchDecision(
                action="match", material_id=material.id, confidence=0.6,
                reasoning="match",
            ),
        )
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(client, supplier.id)
    import_id = upload_response.json()["import_id"]

    response = client.get(f"/price-list-imports/{import_id}")

    assert response.status_code == 200
    assert len(response.json()["entries"]) == 1


def test_apply_match_entry_updates_status_when_all_entries_resolved(
    db_session, make_supplier, make_material, make_user, make_session
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material = make_material()
    client = _admin_client(make_user, make_session)

    matched = [
        MatchedLine(
            extracted=_extracted(raw_name="Known Screen", price=4.0),
            decision=MatchDecision(
                action="match", material_id=material.id, confidence=0.95,
                reasoning="matches",
            ),
        )
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(client, supplier.id)
    body = upload_response.json()
    import_id = body["import_id"]
    entry_id = body["entries"][0]["id"]

    response = client.post(
        f"/price-list-imports/{import_id}/entries/{entry_id}/apply",
        json={"action": "match", "material_id": str(material.id)},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 200

    session.expire_all()
    price_list_import = session.get(PriceListImport, uuid.UUID(import_id))
    assert price_list_import.status == "approved"


def test_apply_skip_leaves_import_pending_until_all_entries_resolved(
    db_session, make_supplier, make_material, make_user, make_session
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material_1 = make_material()
    material_2 = make_material()
    client = _admin_client(make_user, make_session)

    matched = [
        MatchedLine(
            extracted=_extracted(raw_name="Line 1", price=1.0),
            decision=MatchDecision(
                action="match", material_id=material_1.id, confidence=0.5,
                reasoning="unsure",
            ),
        ),
        MatchedLine(
            extracted=_extracted(raw_name="Line 2", price=2.0),
            decision=MatchDecision(
                action="match", material_id=material_2.id, confidence=0.5,
                reasoning="unsure",
            ),
        ),
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(client, supplier.id)
    body = upload_response.json()
    import_id = body["import_id"]
    entry_1_id = body["entries"][0]["id"]

    response = client.post(
        f"/price-list-imports/{import_id}/entries/{entry_1_id}/apply",
        json={"action": "skip"},
        headers={"X-CSRF-Token": CSRF},
    )
    assert response.status_code == 200

    session.expire_all()
    price_list_import = session.get(PriceListImport, uuid.UUID(import_id))
    assert price_list_import.status == "pending_review"


def test_upload_rejects_unsupported_content_type(
    db_session, make_supplier, make_user, make_session
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    response = _upload(client, supplier.id, content_type="text/plain")

    assert response.status_code == 422


def test_upload_returns_404_for_unknown_supplier(make_user, make_session):
    client = _admin_client(make_user, make_session)
    with patch("app.price_ingestion.service.extract_price_list_lines", return_value=[]):
        response = _upload(client, uuid.uuid4())

    assert response.status_code == 404


def test_apply_returns_404_for_unknown_entry(db_session, make_supplier, make_user, make_session):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    matched = []
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(client, supplier.id)
    import_id = upload_response.json()["import_id"]

    response = client.post(
        f"/price-list-imports/{import_id}/entries/{uuid.uuid4()}/apply",
        json={"action": "skip"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def _upload_single_entry(client, supplier, material):
    matched = [
        MatchedLine(
            extracted=_extracted(raw_name="Some Line", price=3.0),
            decision=MatchDecision(
                action="match", material_id=material.id, confidence=0.5,
                reasoning="unsure",
            ),
        )
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        upload_response = _upload(client, supplier.id)
    return upload_response.json()


def test_apply_match_without_material_id_returns_422(
    db_session, make_supplier, make_material, make_user, make_session
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material = make_material()
    client = _admin_client(make_user, make_session)
    body = _upload_single_entry(client, supplier, material)
    entry_id = body["entries"][0]["id"]

    response = client.post(
        f"/price-list-imports/{body['import_id']}/entries/{entry_id}/apply",
        json={"action": "match"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_apply_new_without_internal_sku_returns_422(
    db_session, make_supplier, make_material, make_user, make_session
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material = make_material()
    client = _admin_client(make_user, make_session)
    body = _upload_single_entry(client, supplier, material)
    entry_id = body["entries"][0]["id"]

    response = client.post(
        f"/price-list-imports/{body['import_id']}/entries/{entry_id}/apply",
        json={"action": "new", "canonical_name": "X"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 422


def test_apply_match_with_nonexistent_material_id_returns_404(
    db_session, make_supplier, make_material, make_user, make_session
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    material = make_material()
    client = _admin_client(make_user, make_session)
    body = _upload_single_entry(client, supplier, material)
    entry_id = body["entries"][0]["id"]

    response = client.post(
        f"/price-list-imports/{body['import_id']}/entries/{entry_id}/apply",
        json={"action": "match", "material_id": str(uuid.uuid4())},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 404


def test_upload_response_includes_processing_status_for_failed_line(
    db_session, make_supplier, make_user, make_session
):
    """A line whose retry was exhausted during matching (ADR-0022 §2)
    still comes back as a normal PriceListEntry with
    processing_status="failed" and empty matching fields — not dropped
    (even though its placeholder decision is action="not_found",
    ADR-0025 §5's not-persisted rule applies only to real not_found
    decisions, not failure placeholders), not a 5xx for the whole import."""
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    matched = [
        MatchedLine(
            extracted=_extracted(raw_name="Unmatchable Line", price=9.0),
            decision=MatchDecision(
                action="not_found", material_id=None, confidence=0.0, reasoning="",
            ),
            processing_status="failed",
        )
    ]
    mock_match, mock_extract = _mock_pipeline(matched)
    with mock_match, mock_extract:
        response = _upload(client, supplier.id)

    assert response.status_code == 201
    entry = response.json()["entries"][0]
    assert entry["processing_status"] == "failed"
    assert entry["matched_material_id"] is None
    assert entry["action"] is None


def test_upload_openai_failure_returns_clear_error_not_bare_500(
    db_session, make_supplier, make_user, make_session
):
    session, _material_ids, _supplier_ids, _user_ids = db_session
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)

    with patch(
        "app.price_ingestion.service.extract_price_list_lines",
        side_effect=PriceIngestionError("Не удалось связаться с сервисом распознавания."),
    ):
        response = _upload(client, supplier.id)

    assert response.status_code == 502
    assert response.json()["detail"]


def test_upload_no_session_returns_401(make_supplier):
    supplier = make_supplier()
    client = TestClient(app)
    response = _upload(client, supplier.id)
    assert response.status_code == 401


def test_upload_as_employee_returns_403(make_supplier, make_user, make_session):
    supplier = make_supplier()
    employee = make_user(role="employee")
    employee_session = make_session(employee, csrf_token=CSRF)
    client = _client_as(employee_session)
    response = _upload(client, supplier.id)
    assert response.status_code == 403


def test_upload_as_admin_succeeds(make_supplier, make_user, make_session):
    supplier = make_supplier()
    client = _admin_client(make_user, make_session)
    with patch("app.price_ingestion.service.extract_price_list_lines", return_value=[]), patch(
        "app.price_ingestion.service.match_price_list_lines", return_value=[]
    ):
        response = _upload(client, supplier.id)
    assert response.status_code == 201
