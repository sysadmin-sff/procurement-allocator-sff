"""Color parsing and supplier-facing name resolution for two-color
materials — see ADR-0031. Two literal formats exist in the real catalog,
both handled here and nowhere else (import_real_data.py/xlsx_price_matrix.py
and backfill_color_options.py both call parse_color; OrderDetailPage's
buildOrderText/buildTargetPriceOrderText and the future /orders/:id/print
call resolve_material_name — see ADR-0031 §5 for the full list)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.models.material import Material

logger = logging.getLogger(__name__)

KNOWN_COLORS: frozenset[str] = frozenset({"WHITE", "BRONZE"})
"""Fixed dictionary, not inferred from arbitrary text — a typo like "Bronz"
must never silently create a third color. Extend by adding an entry here
when a new color appears in a future price list (ADR-0031 п.1)."""

_PARENTHETICAL_RE = re.compile(r"\(([A-Za-z]+(?:/[A-Za-z]+)+)\)")
_BARE_RE = re.compile(r"\b([A-Za-z]+)/([A-Za-z]+)\b")


@dataclass(frozen=True)
class ColorParseResult:
    color_options: list[str]
    """Normalized, title-case, in canonical_name order — e.g. ["White",
    "Bronze"], not a set. See ADR-0031 п.1."""
    color_fragment: str
    """Exact substring in canonical_name to replace — includes the
    parentheses for the parenthetical format, bare text otherwise."""
    pattern: Literal["parenthetical", "bare"]


def _normalize_tokens(tokens: list[str]) -> list[str] | None:
    normalized = []
    for token in tokens:
        if token.upper() not in KNOWN_COLORS:
            return None
        normalized.append(token.capitalize())
    return normalized


def parse_color(canonical_name: str) -> ColorParseResult | None:
    """Returns None for: no color found, a single color in parentheses
    (deliberate non-match, ADR-0031 п.1 "Примечание про однoцветные
    материалы"), or a color-shaped token whose word(s) are not in
    KNOWN_COLORS (e.g. a typo). Tries the parenthetical format first, then
    the bare (no-parens) format used by the Screws category."""
    paren_match = _PARENTHETICAL_RE.search(canonical_name)
    if paren_match:
        tokens = paren_match.group(1).split("/")
        if len(tokens) < 2:
            return None
        normalized = _normalize_tokens(tokens)
        if normalized is None:
            return None
        return ColorParseResult(
            color_options=normalized,
            color_fragment=paren_match.group(0),
            pattern="parenthetical",
        )

    for bare_match in _BARE_RE.finditer(canonical_name):
        first, second = bare_match.group(1), bare_match.group(2)
        normalized = _normalize_tokens([first, second])
        if normalized is not None:
            return ColorParseResult(
                color_options=normalized,
                color_fragment=bare_match.group(0),
                pattern="bare",
            )

    return None


def resolve_material_name(material: Material, color: str | None) -> str:
    """Supplier-facing material name with the color ambiguity resolved —
    see ADR-0031 п.4. Pure function: does not decide whether generation
    should be blocked when color is None and color_options is non-empty —
    that is create_orders_for_run's job (ADR-0031 п.4 "calling contract").

    - color_options empty/None -> canonical_name as-is.
    - color_options non-empty, color is None -> canonical_name as-is (the
      caller is responsible for having already blocked this path if it
      shouldn't be reachable).
    - color_options non-empty, color present in color_options ->
      canonical_name with color_fragment replaced by the bare chosen color
      (parens stripped for the parenthetical format).
    - color present but not in color_options -> canonical_name as-is,
      logged as an anomaly (should not happen by construction, since
      Project.color_choice is restricted to the same KNOWN_COLORS
      dictionary, but this function must not crash or invent a color).
    """
    if not material.color_options:
        return material.canonical_name

    if color is None:
        return material.canonical_name

    if color not in material.color_options:
        logger.warning(
            "resolve_material_name: color %r not in color_options %r for material %r",
            color,
            material.color_options,
            material.canonical_name,
        )
        return material.canonical_name

    fragment = material.color_fragment
    new_fragment = f"({color})" if fragment.startswith("(") and fragment.endswith(")") else color
    return material.canonical_name.replace(fragment, new_fragment)
