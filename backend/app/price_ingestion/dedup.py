"""Early chunk-overlap deduplication grouping — see ADR-0022 §1, rewritten
by ADR-0023 after a real-document run showed the original whole-document
embedding-distance approach producing ~85% false positives (see
docs/known-issues.md, "ADR-0022 §1 — ОТКЛЮЧЕНА").

ADR-0023's fix has two parts:

1. Candidate pairs are scoped to lines sharing the same physical page
   number (ExtractedPriceLine.page_number, ADR-0021 §3 — the only page a
   chunk-overlap duplicate can physically occur on is the one page shared
   between two adjacent chunks). A line from page 2 is never compared
   against a line from page 9 — they cannot be chunk-overlap duplicates by
   construction, regardless of embedding distance.
2. Within that scoped set, only exact raw_name match (after whitespace/
   case normalization) is used as the duplicate signal. A secondary
   cosine-distance threshold was investigated and rejected — even
   restricted to same-page candidate pairs on the real reference document,
   genuine chunk-overlap duplicates (e.g. an OCR-misread variant) and
   distinct product-line variants (different SKU/size, e.g. different
   socket shaft lengths) were interleaved with no separating distance gap
   (docs/decisions/0023-price-list-overlap-scoped-dedup.md). Exact-name
   matching alone is the only safe automatic signal; everything else goes
   through its own full matching path.
"""

from __future__ import annotations

import re


def _normalize(raw_name: str) -> str:
    return re.sub(r"\s+", " ", raw_name.strip()).lower()


def group_duplicate_lines(
    raw_names: list[str], page_numbers: list[int]
) -> list[int]:
    """Returns, for each input line (by index), the index of its group's
    representative line. A line with no exact-match neighbor on the same
    page is its own representative.

    Two lines can only be grouped if they share the same page_number (the
    overlap page between the two chunks that produced them) AND their
    raw_name is identical after whitespace/case normalization. Groups are
    formed against the first not-yet-grouped matching line encountered in
    input order, so index i's representative is always <= i."""
    representative_of: list[int] = []
    representatives_by_key: dict[tuple[int, str], int] = {}

    for i, (raw_name, page_number) in enumerate(zip(raw_names, page_numbers, strict=True)):
        key = (page_number, _normalize(raw_name))
        rep = representatives_by_key.get(key)
        if rep is None:
            representatives_by_key[key] = i
            representative_of.append(i)
        else:
            representative_of.append(rep)

    return representative_of
