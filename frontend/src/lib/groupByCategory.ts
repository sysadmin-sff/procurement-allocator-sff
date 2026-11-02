import type { Category } from '../api/types';

/** Minimal shape both ProjectTemplateItem and an adapted BOM row satisfy. */
export interface CategorizedItem {
  material_id: string;
  category_name: string | null | undefined;
  /** Material.internal_sku — orders items inside their category group
   * (ADR-0049). Missing → after the items that have one, in input order. */
  internal_sku?: string | null;
}

/** internal_sku order with the numeric part compared as a number ("X-99" <
 * "X-100"); a missing SKU sorts after any present one. See ADR-0049. */
function compareSku(a: string | null | undefined, b: string | null | undefined): number {
  if (!a || !b) return (a ? 0 : 1) - (b ? 0 : 1);
  return a.localeCompare(b, 'en', { numeric: true });
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
    // Array.prototype.sort is stable, so equal/missing SKUs keep input order.
    items: byCategory.get(category)!.sort((a, b) => compareSku(a.internal_sku, b.internal_sku)),
  }));
}

/** Same order as groupByCategory (category display_order, then
 * internal_sku — ADR-0042/ADR-0049), flattened, for lists that are not
 * rendered as category groups (order items, allocation lines). `getMaterial`
 * resolves an item to its material's category/SKU; an item it can't resolve
 * (lightweight OrderItem, material not loaded yet) goes last, in input
 * order. */
export function orderByCategoryAndSku<T>(
  items: T[],
  getMaterial: (item: T) => { category_name: string | null | undefined; internal_sku: string } | undefined,
  categoryOrder: Map<string, number>,
): T[] {
  const adapted = items.map((item, index) => {
    const material = getMaterial(item);
    return {
      item,
      material_id: String(index),
      category_name: material?.category_name,
      internal_sku: material?.internal_sku,
    };
  });
  return groupByCategory(adapted, categoryOrder).flatMap((group) => group.items.map((a) => a.item));
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
