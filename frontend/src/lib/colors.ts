import type { Material } from '../api/types';

/** Mirrors backend/app/services/material_naming.py KNOWN_COLORS — fixed
 * dictionary, not inferred from arbitrary text, so a typo never silently
 * creates a third color. Extend here (and on the backend) when a new color
 * appears in a future price list. See ADR-0031 п.1. Title-case values match
 * Material.color_options / Project.color_choice exactly, as sent/received
 * over the API — the backend validator only checks .upper() membership, but
 * always stores/returns the value as passed. */
export const KNOWN_COLORS: readonly string[] = ['White', 'Bronze'];

const COLOR_WORD = new RegExp(`\\b(${KNOWN_COLORS.join('|')})\\b`, 'gi');

/** Employees type the project color into its title by hand ("3284 bronze -
 * 1146 27th Ave S"); when Project.color_choice changes, every KNOWN_COLORS
 * word in the title (whole word, any case) becomes the new color in the
 * same case style. A title with no color word, or a cleared color, leaves
 * the title as is — nothing is appended. */
export function retitleWithColor(title: string, color: string | null): string {
  if (color == null) return title;
  return title.replace(COLOR_WORD, (word) => {
    if (word === word.toUpperCase()) return color.toUpperCase();
    if (word === word.toLowerCase()) return color.toLowerCase();
    return color;
  });
}

/** Supplier-facing material name with the color ambiguity resolved — mirrors
 * backend/app/services/material_naming.py resolve_material_name exactly
 * (ADR-0031 п.4), so buildOrderText/buildTargetPriceOrderText (and any
 * future consumer) share one implementation instead of re-parsing
 * canonical_name themselves. Pure function: does not decide whether
 * generation should be blocked when color is null and color_options is
 * non-empty — that is the caller's responsibility (ADR-0031 п.3, enforced
 * server-side and mirrored for UX on AllocationResultPage). */
export function resolveMaterialName(material: Material, color: string | null | undefined): string {
  const colorOptions = material.color_options;
  if (colorOptions == null || colorOptions.length === 0) {
    return material.canonical_name;
  }

  if (color == null) {
    return material.canonical_name;
  }

  if (!colorOptions.includes(color)) {
    return material.canonical_name;
  }

  const fragment = material.color_fragment;
  if (fragment == null) {
    return material.canonical_name;
  }

  const newFragment = fragment.startsWith('(') && fragment.endsWith(')') ? `(${color})` : color;
  return material.canonical_name.replace(fragment, newFragment);
}

/** True if any material in the given set has a non-empty color_options —
 * the trigger condition for both the order-creation block (backend,
 * ADR-0031 п.3) and its UX mirror (AllocationResultPage's disabled button). */
export function hasColorChoiceMaterial(materials: (Material | undefined)[]): boolean {
  return materials.some((m) => m?.color_options != null && m.color_options.length > 0);
}
