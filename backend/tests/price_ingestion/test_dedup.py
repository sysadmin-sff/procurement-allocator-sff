"""Tests for app.price_ingestion.dedup — ADR-0023 chunk-overlap dedup:
candidates scoped to same page_number, exact normalized raw_name match as
the sole duplicate signal (no distance threshold — see dedup.py module
docstring and docs/decisions/0023-price-list-overlap-scoped-dedup.md for
why a secondary distance check was rejected).
"""

from app.price_ingestion.dedup import group_duplicate_lines


def test_identical_raw_name_same_page_are_grouped_with_first_as_representative():
    groups = group_duplicate_lines(
        raw_names=["Screen Type A", "Screen Type A"],
        page_numbers=[3, 3],
    )
    assert groups == [0, 0]


def test_identical_raw_name_different_page_are_not_grouped():
    # A line from chunk 0 (page 2) and a line from chunk 5 (page 11) can
    # never be a chunk-overlap duplicate of each other, even with
    # identical text — they are not on a shared overlap page.
    groups = group_duplicate_lines(
        raw_names=["Screen Type A", "Screen Type A"],
        page_numbers=[2, 11],
    )
    assert groups == [0, 1]


def test_different_raw_name_same_page_are_not_grouped():
    groups = group_duplicate_lines(
        raw_names=["Screen Type A", "Screen Type B"],
        page_numbers=[3, 3],
    )
    assert groups == [0, 1]


def test_normalization_ignores_case_and_extra_whitespace():
    groups = group_duplicate_lines(
        raw_names=["Screen Type A", "  screen type a  "],
        page_numbers=[3, 3],
    )
    assert groups == [0, 0]


def test_near_duplicate_text_on_same_page_is_not_grouped_without_exact_match():
    # ADR-0023: a secondary distance-based signal was investigated and
    # rejected — real product-line variants (different sizes) sit at
    # embedding distances indistinguishable from genuine chunk-overlap
    # duplicates on the real reference document. Only exact text match
    # (after normalization) is used; anything else must go through its
    # own independent matching call, even if it's a near-miss like this.
    groups = group_duplicate_lines(
        raw_names=["FLAT SPLINE .315 1000'", "FLAT SPLINE .315 1500'"],
        page_numbers=[9, 9],
    )
    assert groups == [0, 1]


def test_three_lines_two_identical_on_shared_page_one_different_page():
    groups = group_duplicate_lines(
        raw_names=["Item X", "Item X", "Item X"],
        page_numbers=[5, 5, 6],
    )
    assert groups == [0, 0, 2]


def test_single_line_is_its_own_representative():
    groups = group_duplicate_lines(raw_names=["Solo Item"], page_numbers=[4])
    assert groups == [0]


def test_empty_input_returns_empty_list():
    assert group_duplicate_lines(raw_names=[], page_numbers=[]) == []


def test_boundary_line_from_chunk_zero_never_grouped_with_line_from_distant_chunk():
    # Regression guard for the exact bug ADR-0023 fixed: comparing every
    # line in the document against every other line regardless of chunk
    # origin. Simulate a document where chunk 0 covers pages 1-3 and a far
    # later chunk covers pages 11-13 — identical text on page 1 vs page 13
    # must never be grouped, they cannot share an overlap page.
    groups = group_duplicate_lines(
        raw_names=["Common Header Row"] * 2,
        page_numbers=[1, 13],
    )
    assert groups == [0, 1]
