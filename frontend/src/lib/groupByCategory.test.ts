import { describe, expect, it } from 'vitest';
import { buildCategoryOrder, groupByCategory, type CategorizedItem } from './groupByCategory';
import type { Category } from '../api/types';

function item(material_id: string, category_name: string | null | undefined): CategorizedItem {
  return { material_id, category_name };
}

function category(name: string, display_order: number): Category {
  return {
    id: `cat-${name}`,
    name,
    sku_prefix: name.slice(0, 4).toUpperCase(),
    requires_single_supplier: false,
    next_sku_number: 1,
    display_order,
    created_at: '2026-01-01T00:00:00Z',
  };
}

describe('groupByCategory', () => {
  it('sorts groups by the display_order lookup, not first-appearance order', () => {
    const items = [
      item('m1', 'Screws'), // display_order 7, appears first in input
      item('m2', 'Doors'), // display_order 0
      item('m3', 'Mesh'), // display_order 5
    ];
    const order = buildCategoryOrder([
      category('Doors', 0),
      category('Mesh', 5),
      category('Screws', 7),
    ]);

    const groups = groupByCategory(items, order);

    expect(groups.map((g) => g.category)).toEqual(['Doors', 'Mesh', 'Screws']);
  });

  it('places "Без категории" (null/empty category_name) last, after every named group', () => {
    const items = [
      item('m1', ''),
      item('m2', 'Screws'),
      item('m3', null),
      item('m4', 'Doors'),
    ];
    const order = buildCategoryOrder([category('Doors', 0), category('Screws', 7)]);

    const groups = groupByCategory(items, order);

    expect(groups.map((g) => g.category)).toEqual(['Doors', 'Screws', null]);
    // Both the empty-string and null category_name items land in the same
    // single trailing group, not two separate ones.
    expect(groups.at(-1)?.items.map((i) => i.material_id)).toEqual(['m1', 'm3']);
  });

  it('places a category name absent from the lookup after every known category, before "Без категории"', () => {
    const items = [
      item('m1', 'Unknown Category'),
      item('m2', 'Doors'),
      item('m3', null),
    ];
    // "Unknown Category" has no entry in the lookup -- e.g. a stale client
    // cache momentarily out of sync with the DB.
    const order = buildCategoryOrder([category('Doors', 0)]);

    const groups = groupByCategory(items, order);

    expect(groups.map((g) => g.category)).toEqual(['Doors', 'Unknown Category', null]);
  });

  it('keeps all items for a category together regardless of interleaving in the input', () => {
    const items = [
      item('m1', 'Screws'),
      item('m2', 'Doors'),
      item('m3', 'Screws'),
      item('m4', 'Doors'),
    ];
    const order = buildCategoryOrder([category('Doors', 0), category('Screws', 7)]);

    const groups = groupByCategory(items, order);

    expect(groups).toHaveLength(2);
    expect(groups[0].category).toBe('Doors');
    expect(groups[0].items.map((i) => i.material_id)).toEqual(['m2', 'm4']);
    expect(groups[1].category).toBe('Screws');
    expect(groups[1].items.map((i) => i.material_id)).toEqual(['m1', 'm3']);
  });
});

describe('buildCategoryOrder', () => {
  it('maps each category name to its display_order', () => {
    const result = buildCategoryOrder([category('Doors', 0), category('Gutter', 1)]);

    expect(result.get('Doors')).toBe(0);
    expect(result.get('Gutter')).toBe(1);
    expect(result.get('Unknown')).toBeUndefined();
  });
});
