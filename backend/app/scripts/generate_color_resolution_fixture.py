"""One-off generator for the cross-validation fixture consumed by
frontend/src/lib/colorResolution.crossvalidation.test.ts — see ADR-0031 п.4/п.5
"Отклонено" (duplicated resolve_material_name across backend/frontend) and
docs/known-issues.md.

Parses the real price-matrix xlsx (the same file import_real_data.py loads),
takes every material parse_color recognized (147 as of ADR-0031 Step 0), and
for each one records backend resolve_material_name's output for every color
in KNOWN_COLORS — not just the material's own two options, so the fixture
also exercises the "color not in color_options" branch (falls back to
canonical_name as-is) on the frontend side. Output is deliberately checked
into the repo (not regenerated at test time): the fixture must only change
when someone re-runs this script deliberately, so a future backend change to
parse_color's patterns doesn't silently rewrite the "reference" answer out
from under the test that is supposed to catch that exact drift.

Usage:
    python -m app.scripts.generate_color_resolution_fixture
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.scripts.xlsx_price_matrix import parse_price_matrix
from app.services.material_naming import KNOWN_COLORS, resolve_material_name

XLSX_PATH = Path(__file__).resolve().parents[2] / "data" / "import" / "materials_price_matrix.xlsx"
OUTPUT_PATH = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "lib"
    / "__fixtures__"
    / "colorResolutionRealCatalog.json"
)

# Title-case mirror of KNOWN_COLORS (which is upper-case, e.g. "WHITE") — the
# actual color values passed around the app (Material.color_options,
# Project.color_choice) are title-case ("White"), see material_naming.py's
# own _normalize_tokens.
COLORS_TO_TEST = sorted(color.capitalize() for color in KNOWN_COLORS)


def main() -> None:
    workbook = parse_price_matrix(XLSX_PATH)
    colored_materials = [m for m in workbook.materials if m.color_options]

    rows = []
    for material in colored_materials:
        material_obj = SimpleNamespace(
            canonical_name=material.description,
            color_options=material.color_options,
            color_fragment=material.color_fragment,
        )
        resolved = {color: resolve_material_name(material_obj, color) for color in COLORS_TO_TEST}
        rows.append(
            {
                "internal_sku": material.internal_sku,
                "canonical_name": material.description,
                "color_options": material.color_options,
                "color_fragment": material.color_fragment,
                "resolved": resolved,
            }
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps({"colors_tested": COLORS_TO_TEST, "materials": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(rows)} materials x {len(COLORS_TO_TEST)} colors to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
