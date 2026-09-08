"""Tests for xlsx_price_matrix.py's color-field population — see ADR-0031
"Последствия": future imports must get color_options/color_fragment at
parse time, not only via the one-time backfill script."""

from app.scripts.xlsx_price_matrix import MaterialRow
from app.services.material_naming import parse_color


def test_material_row_carries_color_fields_when_present():
    description = 'Super Gutter End Cap 5" (White/Bronze)'
    parsed = parse_color(description)
    row = MaterialRow(
        internal_sku="GUTR-001",
        description=description,
        category="Gutter",
        unit="pcs",
        used_fallback_unit=False,
        row_number=2,
        color_options=parsed.color_options if parsed else None,
        color_fragment=parsed.color_fragment if parsed else None,
    )
    assert row.color_options == ["White", "Bronze"]
    assert row.color_fragment == "(White/Bronze)"


def test_material_row_color_fields_default_to_none():
    row = MaterialRow(
        internal_sku="MISC-001",
        description="Generic Bracket 4in",
        category=None,
        unit="pcs",
        used_fallback_unit=False,
        row_number=5,
    )
    assert row.color_options is None
    assert row.color_fragment is None
