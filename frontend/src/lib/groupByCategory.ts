import type { Category } from '../api/types';

/** Minimal shape both ProjectTemplateItem and an adapted BOM row satisfy. */
export interface CategorizedItem {
  material_id: string;
  category_name: string | null | undefined;
}

/** Builds the name -> display_order lookup groupByCategory needs, from the
 * Category[] useCategories() already loads (ADR-0042). */
export function buildCategoryOrder(categories: Category[]): Map<string, number> {
  return new Map(categories.map((c) => [c.name, c.display_order]));
}

export interface CategoryGroup<T> {
  category: string | null;
  items: T[];
}

/**
 * Groups items by category_name, ordering the resulting groups by
 * Category.display_order (ADR-0042) — not first-appearance, not alphabetical.
 * `categoryOrder` is a name -> display_order lookup, built by the caller from
 * useCategories() (GET /categories is already sorted by display_order, so
 * the lookup itself needs no re-sorting). A category name absent from the
 * lookup (e.g. a stale client cache momentarily out of sync with the DB)
 * sorts after every known category but still before "Без категории", which
 * stays hard-coded last regardless of order — items with no category
 * (null/empty string) always fall into that single trailing group.
 */
export function groupByCategory<T extends CategorizedItem>(
  items: T[],
  categoryOrder: Map<string, number>,
): CategoryGroup<T>[] {
  const byCategory = new Map<string | null, T[]>();

  for (const item of items) {
    const category = item.category_name || null;
    if (!byCategory.has(category)) byCategory.set(category, []);
    byCategory.get(category)!.push(item);
  }

  const namedCategories = [...byCategory.keys()]
    .filter((c): c is string => c !== null)
    .sort((a, b) => (categoryOrder.get(a) ?? Infinity) - (categoryOrder.get(b) ?? Infinity));
  const orderedCategories = [...namedCategories, ...(byCategory.has(null) ? [null] : [])];

  return orderedCategories.map((category) => ({
    category,
    items: byCategory.get(category)!,
  }));
}

/** Counts occurrences of each material_id — used to flag duplicate rows
 * (same material added more than once) without blocking the add itself. */
export function countByMaterialId<T extends CategorizedItem>(items: T[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of items) {
    counts.set(item.material_id, (counts.get(item.material_id) ?? 0) + 1);
  }
  return counts;
}
