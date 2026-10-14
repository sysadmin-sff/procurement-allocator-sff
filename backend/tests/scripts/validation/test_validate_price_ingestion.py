"""Tests for the price-ingestion dual-model validation script — see
ADR-0044 §5. extract_price_list_lines/match_price_list_lines are mocked at
their module boundary (no real OpenAI call); the behavior under test is
that both models actually run, in the right order, with settings restored
after.
"""

import uuid
from unittest.mock import patch

from app.core.config import settings
from app.price_ingestion.extraction import ExtractedPriceLine
from app.price_ingestion.matching import MatchDecision, MatchedLine
from app.scripts.validation.validate_price_ingestion import run_dual_model


def _matched_line(material_id):
    return MatchedLine(
        extracted=ExtractedPriceLine(
            raw_name="Widget",
            raw_sku=None,
            price=10.0,
            currency="USD",
            availability=None,
            min_order_qty=None,
            page_number=1,
        ),
        decision=MatchDecision(
            action="match", material_id=material_id, confidence=0.9, reasoning="x"
        ),
    )


def test_run_dual_model_calls_pipeline_once_per_model_and_restores_setting():
    original_model = settings.openai_price_ingestion_model
    observed_models = []

    def fake_match(db, supplier_id, lines):
        observed_models.append(settings.openai_price_ingestion_model)
        return [_matched_line(uuid.uuid4())]

    with patch(
        "app.scripts.validation.validate_price_ingestion.extract_price_list_lines",
        return_value=[],
    ), patch(
        "app.scripts.validation.validate_price_ingestion.match_price_list_lines",
        side_effect=fake_match,
    ):
        run_dual_model(
            db=None, supplier_id=uuid.uuid4(), file_bytes=b"x", content_type="application/pdf"
        )

    assert observed_models == ["gpt-5.6-sol", "gpt-5.6-luna"]
    assert settings.openai_price_ingestion_model == original_model


def test_run_dual_model_returns_comparison_per_line():
    material_id = uuid.uuid4()

    with patch(
        "app.scripts.validation.validate_price_ingestion.extract_price_list_lines",
        return_value=[],
    ), patch(
        "app.scripts.validation.validate_price_ingestion.match_price_list_lines",
        return_value=[_matched_line(material_id)],
    ):
        comparisons = run_dual_model(
            db=None, supplier_id=uuid.uuid4(), file_bytes=b"x", content_type="application/pdf"
        )

    assert len(comparisons) == 1
    assert comparisons[0].needs_manual_review is False


def test_run_dual_model_restores_setting_even_if_pipeline_raises():
    # Deliberately distinct from both _SOL_MODEL/_LUNA_MODEL so a restore
    # that merely "happens to" leave the setting at the sol default can't
    # pass by coincidence (it previously did, since the real config
    # default IS gpt-5.6-sol -- see ADR-0044 review history).
    settings.openai_price_ingestion_model = "some-other-model-entirely"
    original_model = settings.openai_price_ingestion_model

    try:
        with patch(
            "app.scripts.validation.validate_price_ingestion.extract_price_list_lines",
            side_effect=RuntimeError("boom"),
        ):
            try:
                run_dual_model(
                    db=None,
                    supplier_id=uuid.uuid4(),
                    file_bytes=b"x",
                    content_type="application/pdf",
                )
            except RuntimeError:
                pass

        assert settings.openai_price_ingestion_model == original_model
    finally:
        settings.openai_price_ingestion_model = original_model
