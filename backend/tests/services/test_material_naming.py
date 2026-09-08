"""Tests for color parsing and resolve_material_name — see ADR-0031 п.1/п.4."""

import logging

from app.services.material_naming import ColorParseResult, parse_color, resolve_material_name


def test_parse_color_parenthetical_two_colors():
    result = parse_color('Super Gutter End Cap 5" (White/Bronze)')
    assert result == ColorParseResult(
        color_options=["White", "Bronze"],
        color_fragment="(White/Bronze)",
        pattern="parenthetical",
    )


def test_parse_color_parenthetical_reverse_order_preserved():
    result = parse_color('Door Blank with 8" Kick Plate (Bronze/White)')
    assert result.color_options == ["Bronze", "White"]
    assert result.color_fragment == "(Bronze/White)"


def test_parse_color_bare_screws_format():
    result = parse_color('12 x 3/4" Bronze/White Stainless steel')
    assert result == ColorParseResult(
        color_options=["Bronze", "White"],
        color_fragment="Bronze/White",
        pattern="bare",
    )


def test_parse_color_bare_white_bronze_order():
    result = parse_color('10 x 3/4" White/Bronze Galvanized')
    assert result.color_options == ["White", "Bronze"]
    assert result.color_fragment == "White/Bronze"


def test_parse_color_single_color_in_parens_returns_none():
    result = parse_color("E-Fascia x 24' (White)")
    assert result is None


def test_parse_color_no_color_word_returns_none():
    result = parse_color('3" Panel WITHOUT Fan Beam (.024)')
    assert result is None


def test_parse_color_no_color_at_all_returns_none():
    result = parse_color("Generic Bracket 4in")
    assert result is None


def test_parse_color_unknown_color_word_in_parens_not_matched():
    # "Bronz" is a typo, not a known color — must not silently match.
    result = parse_color("Widget (Bronz/White)")
    assert result is None


class _FakeMaterial:
    """Minimal stand-in for app.models.material.Material — resolve_material_name
    only reads canonical_name/color_options/color_fragment, so a real ORM
    instance is unnecessary here."""

    def __init__(self, canonical_name, color_options=None, color_fragment=None):
        self.canonical_name = canonical_name
        self.color_options = color_options
        self.color_fragment = color_fragment


def test_resolve_material_name_no_color_options_returns_as_is():
    material = _FakeMaterial("E-Fascia x 24' (White)")
    assert resolve_material_name(material, None) == "E-Fascia x 24' (White)"
    assert resolve_material_name(material, "White") == "E-Fascia x 24' (White)"


def test_resolve_material_name_options_present_color_none_returns_as_is():
    material = _FakeMaterial(
        'Super Gutter End Cap 5" (White/Bronze)',
        color_options=["White", "Bronze"],
        color_fragment="(White/Bronze)",
    )
    assert resolve_material_name(material, None) == 'Super Gutter End Cap 5" (White/Bronze)'


def test_resolve_material_name_options_present_color_valid_parenthetical():
    material = _FakeMaterial(
        'Super Gutter End Cap 5" (White/Bronze)',
        color_options=["White", "Bronze"],
        color_fragment="(White/Bronze)",
    )
    assert resolve_material_name(material, "White") == 'Super Gutter End Cap 5" (White)'
    assert resolve_material_name(material, "Bronze") == 'Super Gutter End Cap 5" (Bronze)'


def test_resolve_material_name_options_present_color_valid_bare():
    material = _FakeMaterial(
        '12 x 3/4" Bronze/White Stainless steel',
        color_options=["Bronze", "White"],
        color_fragment="Bronze/White",
    )
    assert resolve_material_name(material, "White") == '12 x 3/4" White Stainless steel'
    assert resolve_material_name(material, "Bronze") == '12 x 3/4" Bronze Stainless steel'


def test_resolve_material_name_color_not_in_options_returns_as_is_and_logs(caplog):
    material = _FakeMaterial(
        'Super Gutter End Cap 5" (White/Bronze)',
        color_options=["White", "Bronze"],
        color_fragment="(White/Bronze)",
    )
    with caplog.at_level(logging.WARNING):
        result = resolve_material_name(material, "Green")
    assert result == 'Super Gutter End Cap 5" (White/Bronze)'
    assert "Green" in caplog.text
