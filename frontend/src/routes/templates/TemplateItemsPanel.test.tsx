import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TemplateItemsPanel } from './TemplateItemsPanel';
import { categoriesApi } from '../../api/categories';
import { materialsApi } from '../../api/materials';
import type { Category, Material, ProjectTemplate } from '../../api/types';

vi.mock('../../api/materials', () => ({
  materialsApi: { list: vi.fn() },
}));
vi.mock('../../api/categories', () => ({
  categoriesApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const materialsListMock = vi.mocked(materialsApi.list);
const categoriesListMock = vi.mocked(categoriesApi.list);

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

const doorHandle: Material = {
  id: 'mat-1',
  internal_sku: 'DOOR-STD',
  canonical_name: 'Дверная ручка',
  category_name: 'Двери',
  unit: 'шт',
  attributes: {},
};

const windowSeal: Material = {
  id: 'mat-2',
  internal_sku: 'WIN-SEAL',
  canonical_name: 'Уплотнитель окна',
  category_name: 'Окна',
  unit: 'м',
  attributes: {},
};

function template(items: ProjectTemplate['items']): ProjectTemplate {
  return { id: 't1', name: 'Шаблон', created_at: '2026-01-10T12:00:00Z', items };
}

describe('TemplateItemsPanel', () => {
  beforeEach(() => {
    categoriesListMock.mockResolvedValue([category('Двери', 0), category('Окна', 1)]);
  });

  it('groups items by Category.display_order (ADR-0042), not first-appearance, with items missing a category last', async () => {
    materialsListMock.mockResolvedValue([doorHandle, windowSeal]);
    // display_order says Двери (0) before Окна (1) -- input order is the
    // opposite (Окна's item comes first), so a regression to first-appearance
    // ordering would put Окна first and fail this test.
    categoriesListMock.mockResolvedValue([category('Двери', 0), category('Окна', 1)]);
    const t = template([
      { id: 'i1', material_id: 'mat-2', canonical_name: 'Уплотнитель окна', unit: 'м', category_name: 'Окна', internal_sku: 'TPL-001' },
      { id: 'i2', material_id: 'mat-3', canonical_name: 'Без категории материал', unit: 'шт', category_name: '', internal_sku: 'TPL-001' },
      { id: 'i3', material_id: 'mat-1', canonical_name: 'Дверная ручка', unit: 'шт', category_name: 'Двери', internal_sku: 'TPL-001' },
      { id: 'i4', material_id: 'mat-4', canonical_name: 'Ещё окно', unit: 'шт', category_name: 'Окна', internal_sku: 'TPL-001' },
    ]);

    render(
      <TemplateItemsPanel
        template={t}
        
        onAddItem={vi.fn()}
        onRemoveItem={vi.fn()}
      />,
    );

    // useCategories() resolves asynchronously -- wait for its result to
    // reach the DOM (groupByCategory can't sort by display_order until
    // categoriesListMock's promise settles) before reading row order.
    await screen.findByText('Двери');

    const headers = screen.getAllByRole('row').map((row) => row.textContent ?? '');
    // Group headers appear in display_order: Двери (0), Окна (1), then "Без категории" last.
    const groupHeaderTexts = ['Двери', 'Окна', 'Без категории'];
    const positions = groupHeaderTexts.map((text) => headers.findIndex((h) => h.includes(text)));

    expect(positions.every((p) => p !== -1)).toBe(true);
    expect(positions[0]).toBeLessThan(positions[1]);
    expect(positions[1]).toBeLessThan(positions[2]);
  });

  it('puts a category unknown to the loaded categories list last, before "Без категории"', async () => {
    materialsListMock.mockResolvedValue([doorHandle, windowSeal]);
    // Only Окна is in the loaded categories list -- Двери is absent (e.g.
    // stale client cache) and must still render, sorted after every known
    // category but before "Без категории".
    categoriesListMock.mockResolvedValue([category('Окна', 0)]);
    const t = template([
      { id: 'i1', material_id: 'mat-1', canonical_name: 'Дверная ручка', unit: 'шт', category_name: 'Двери', internal_sku: 'TPL-001' },
      { id: 'i2', material_id: 'mat-3', canonical_name: 'Без категории материал', unit: 'шт', category_name: '', internal_sku: 'TPL-001' },
      { id: 'i3', material_id: 'mat-2', canonical_name: 'Уплотнитель окна', unit: 'м', category_name: 'Окна', internal_sku: 'TPL-001' },
    ]);

    render(
      <TemplateItemsPanel
        template={t}
        
        onAddItem={vi.fn()}
        onRemoveItem={vi.fn()}
      />,
    );

    await screen.findByText('Окна');

    const headers = screen.getAllByRole('row').map((row) => row.textContent ?? '');
    const groupHeaderTexts = ['Окна', 'Двери', 'Без категории'];
    const positions = groupHeaderTexts.map((text) => headers.findIndex((h) => h.includes(text)));

    expect(positions.every((p) => p !== -1)).toBe(true);
    expect(positions[0]).toBeLessThan(positions[1]);
    expect(positions[1]).toBeLessThan(positions[2]);
  });

  it('does not block adding a material already in the list, and highlights both rows as duplicates', async () => {
    const user = userEvent.setup();
    materialsListMock.mockResolvedValue([doorHandle, windowSeal]);

    const existingItem = { id: 'i1', material_id: 'mat-1', canonical_name: 'Дверная ручка', unit: 'шт', category_name: 'Двери', internal_sku: 'TPL-001' };
    const t = template([existingItem]);
    const onAddItem = vi.fn().mockResolvedValue(undefined);

    render(
      <TemplateItemsPanel
        template={t}
        
        onAddItem={onAddItem}
        onRemoveItem={vi.fn()}
      />,
    );

    const comboInput = screen.getByPlaceholderText('Название или артикул…');
    await user.type(comboInput, 'ручка');
    const listbox = await screen.findByRole('listbox');
    const { getByText } = within(listbox);
    await user.click(getByText(doorHandle.canonical_name));
    await user.click(screen.getByRole('button', { name: /^добавить$/i }));

    // Not blocked: onAddItem is still called with the duplicate material id.
    expect(onAddItem).toHaveBeenCalledWith('mat-1');
  });

  it('keeps the selection for a retry when adding fails, without an unhandled rejection', async () => {
    const user = userEvent.setup();
    materialsListMock.mockResolvedValue([doorHandle, windowSeal]);
    const onAddItem = vi.fn().mockRejectedValue(new Error('duplicate'));

    render(
      <TemplateItemsPanel
        template={template([])}
        
        onAddItem={onAddItem}
        onRemoveItem={vi.fn()}
      />,
    );

    await user.type(screen.getByPlaceholderText('Название или артикул…'), 'ручка');
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByText(doorHandle.canonical_name));
    const addButton = screen.getByRole('button', { name: /^добавить$/i });
    await user.click(addButton);
    await waitFor(() => expect(addButton).toBeEnabled());

    await user.click(addButton);

    expect(onAddItem).toHaveBeenCalledTimes(2);
    expect(onAddItem).toHaveBeenLastCalledWith('mat-1');
  });

  it('marks two rows sharing a material_id as duplicates, and stops marking them once only one remains', () => {
    materialsListMock.mockResolvedValue([doorHandle, windowSeal]);
    const dup = template([
      { id: 'i1', material_id: 'mat-1', canonical_name: 'Дверная ручка', unit: 'шт', category_name: 'Двери', internal_sku: 'TPL-001' },
      { id: 'i2', material_id: 'mat-1', canonical_name: 'Дверная ручка', unit: 'шт', category_name: 'Двери', internal_sku: 'TPL-001' },
    ]);

    const { rerender } = render(
      <TemplateItemsPanel
        template={dup}
        
        onAddItem={vi.fn()}
        onRemoveItem={vi.fn()}
      />,
    );

    const duplicateBadges = screen.getAllByText('дубль');
    expect(duplicateBadges).toHaveLength(2);

    const single = template([
      { id: 'i1', material_id: 'mat-1', canonical_name: 'Дверная ручка', unit: 'шт', category_name: 'Двери', internal_sku: 'TPL-001' },
    ]);
    rerender(
      <TemplateItemsPanel
        template={single}
        
        onAddItem={vi.fn()}
        onRemoveItem={vi.fn()}
      />,
    );

    expect(screen.queryByText('дубль')).not.toBeInTheDocument();
  });

  it('orders items inside a category by the material internal_sku (ADR-0049)', async () => {
    materialsListMock.mockResolvedValue([skuPatio2x3, skuOpenBack, skuPatio2x2]);
    categoriesListMock.mockResolvedValue([category('Profil', 3)]);
    const t = template([
      { id: 'i9', material_id: skuPatio2x3.id, canonical_name: skuPatio2x3.canonical_name, unit: 'pcs', category_name: 'Profil', internal_sku: skuPatio2x3.internal_sku },
      { id: 'i3', material_id: skuOpenBack.id, canonical_name: skuOpenBack.canonical_name, unit: 'pcs', category_name: 'Profil', internal_sku: skuOpenBack.internal_sku },
      { id: 'i6', material_id: skuPatio2x2.id, canonical_name: skuPatio2x2.canonical_name, unit: 'pcs', category_name: 'Profil', internal_sku: skuPatio2x2.internal_sku },
    ]);

    render(<TemplateItemsPanel template={t}  onAddItem={vi.fn()} onRemoveItem={vi.fn()} />);

    await waitFor(() => {
      const rendered = [...document.querySelectorAll('td')]
        .map((td) => td.textContent)
        .filter((text): text is string => skuExpectedNames.includes(text ?? ''));
      expect(rendered).toEqual(skuExpectedNames);
    });
  });
});

const skuOpenBack = {
  id: 'mat-p3',
  internal_sku: 'PROF-003',
  canonical_name: "1 x 2 Open Back x .040 min. x 30' (White/Bronze)",
  category_name: 'Profil',
  unit: 'pcs',
  attributes: {},
};
const skuPatio2x2 = {
  id: 'mat-p6',
  internal_sku: 'PROF-006',
  canonical_name: "2 x 2 x .045 Patio x 24' (White/Bronze)",
  category_name: 'Profil',
  unit: 'pcs',
  attributes: {},
};
const skuPatio2x3 = {
  id: 'mat-p9',
  internal_sku: 'PROF-009',
  canonical_name: "2 x 3 x .045 Patio x 30' (White/Bronze)",
  category_name: 'Profil',
  unit: 'pcs',
  attributes: {},
};
// Input order deliberately not SKU order: PROF-009, PROF-003, PROF-006.
const skuExpectedNames = [skuOpenBack.canonical_name, skuPatio2x2.canonical_name, skuPatio2x3.canonical_name];
