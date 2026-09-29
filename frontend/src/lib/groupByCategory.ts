/** Minimal shape both ProjectTemplateItem and an adapted BOM row satisfy. */
export interface CategorizedItem {
  material_id: string;
  category_name: string | null | undefined;
}

export interface CategoryGroup<T> {
  category: string | null;
  items: T[];
}

/**
 * Groups items by category_name, preserving each category's first-appearance
 * order (not alphabetical). Items with no category (null/empty string) fall
 * into a single "Без категории" group, always last regardless of where it'd
 * otherwise sort.
 */
export function groupByCategory<T extends CategorizedItem>(items: T[]): CategoryGroup<T>[] {
  const order: (string | null)[] = [];
  const byCategory = new Map<string | null, T[]>();

  for (const item of items) {
    const category = item.category_name || null;
    if (!byCategory.has(category)) {
      byCategory.set(category, []);
      order.push(category);
    }
    byCategory.get(category)!.push(item);
  }

  const orderedCategories = [...order.filter((c) => c !== null), ...(byCategory.has(null) ? [null] : [])];

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
