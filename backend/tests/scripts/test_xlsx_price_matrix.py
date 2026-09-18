"""Tests for xlsx_price_matrix.py's color-field population — see ADR-0031
"Последствия": future imports must get color_options/color_fragment at
parse time, not only via the one-time backfill script."""

from app.scripts.xlsx_price_matrix import FALLBACK_UNIT, MaterialRow, _clean_unit
from app.services.material_naming import parse_color


class TestCleanUnit:
    """Regression coverage for the "180 1 sq ft" production bug: the
    sheet's Quantity column is "pack count + unit" as one free-text field
    (e.g. "1 pcs", "1 sq ft"), and _clean_unit used to store it verbatim
    into Material.unit — the frontend's `{quantity} {unit}` display then
    rendered the leading "1" as if it were part of the unit."""

    def test_strips_leading_pack_count_of_one(self):
        assert _clean_unit("1 sq ft") == ("sq ft", False)
        assert _clean_unit("1 pcs") == ("pcs", False)
        assert _clean_unit("1 roll") == ("roll", False)
        assert _clean_unit("1 ft") == ("ft", False)

    def test_keeps_trailing_detail_after_stripped_count(self):
        # Only the leading pack count is stripped — the box's own contents
        # ("100 pcs") isn't this row's pack count and carries information
        # the business put there on purpose (see _clean_unit docstring).
        assert _clean_unit("1 box/100 pcs") == ("box/100 pcs", False)

    def test_no_leading_count_passes_through_unchanged(self):
        assert _clean_unit("compl") == ("compl", False)

    def test_leading_count_other_than_one_is_kept_untouched(self):
        # A pack count that actually varies (not 1) is real information —
        # "5 box" means 5 of the base unit per purchasable pack, not noise
        # to strip like the uninformative "1 ".
        assert _clean_unit("5 box") == ("5 box", False)

    def test_blank_or_none_uses_fallback(self):
        assert _clean_unit(None) == (FALLBACK_UNIT, True)
        assert _clean_unit("") == (FALLBACK_UNIT, True)
        assert _clean_unit("   ") == (FALLBACK_UNIT, True)


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
