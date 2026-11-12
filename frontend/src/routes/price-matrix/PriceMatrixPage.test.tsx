import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PriceMatrixPage } from './PriceMatrixPage';
import { pricesApi } from '../../api/prices';
import { categoriesApi } from '../../api/categories';
import type { PriceMatrix, PriceMatrixCell, PriceMatrixSupplier } from '../../api/types';

vi.mock('../../api/prices', () => ({
  pricesApi: { matrix: vi.fn(), history: vi.fn() },
}));
vi.mock('../../api/categories', () => ({
  categoriesApi: { list: vi.fn() },
}));

const matrixMock = vi.mocked(pricesApi.matrix);
const historyMock = vi.mocked(pricesApi.history);
const categoriesMock = vi.mocked(categoriesApi.list);

function supplier(overrides: Partial<PriceMatrixSupplier>): PriceMatrixSupplier {
  return {
    id: 'sup',
    name: 'Supplier',
    short_name: null,
    is_active_for_allocation: true,
    last_price_date: '2026-11-10',
    days_since_update: 2,
    is_stale: false,
    active_price_count: 1,
    changes: { up: 0, down: 0, new: 0, same: 0 },
    ...overrides,
  };
}

function cell(overrides: Partial<PriceMatrixCell>): PriceMatrixCell {
  return {
    supplier_id: 'sup',
    price_id: 'p',
    price: 10,
    currency: 'USD',
    valid_from: '2026-11-01',
    baseline_price: null,
    baseline_valid_from: null,
    change: 'same',
    change_pct: null,
    is_cheapest: false,
    ...overrides,
  };
}

function fixture(): PriceMatrix {
  return {
    as_of: '2026-11-12',
    compare_to: null,
    stale_after_days: 30,
    summary: { up: 1, down: 1, new: 0, same: 1 },
    suppliers: [
      supplier({ id: 'ems', short_name: 'EMS', changes: { up: 0, down: 1, new: 0, same: 0 } }),
      supplier({
        id: 'fast',
        name: 'Fasteners Inc',
        short_name: 'Fasteners',
        is_stale: true,
        last_price_date: '2026-09-01',
        days_since_update: 72,
      }),
    ],
    rows: [
      {
        material_id: 'door',
        internal_sku: 'DR-1',
        canonical_name: 'Door Blank 36x80',
        unit: 'pcs',
        category_name: 'Doors',
        cells: [
          cell({
            supplier_id: 'ems',
            price: 48,
            change: 'down',
            baseline_price: 50,
            baseline_valid_from: '2026-09-01',
            change_pct: -4,
            is_cheapest: true,
          }),
          cell({ supplier_id: 'fast', price: 49.5, change: 'up', baseline_price: 47, baseline_valid_from: '2026-06-01' }),
        ],
      },
      {
        material_id: 'hinge',
        internal_sku: 'DR-2',
        canonical_name: 'Hinges',
        unit: 'pcs',
        category_name: 'Doors',
        cells: [cell({ supplier_id: 'ems', price: 1.85 })],
      },
      {
        material_id: 'screw',
        internal_sku: 'FX-1',
        canonical_name: 'Screw',
        unit: 'box',
        category_name: 'Fasteners',
        cells: [],
      },
    ],
  };
}

function renderPage(initialUrl = '/prices') {
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <Routes>
        <Route path="/prices" element={<PriceMatrixPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('PriceMatrixPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    matrixMock.mockResolvedValue(fixture());
    categoriesMock.mockResolvedValue([
      { id: 'c1', name: 'Doors', display_order: 1 } as never,
      { id: 'c2', name: 'Fasteners', display_order: 2 } as never,
    ]);
  });

  it('renders materials by category, suppliers as columns and change colors', async () => {
    renderPage();

    expect(await screen.findByText('Door Blank 36x80')).toBeInTheDocument();
    expect(matrixMock).toHaveBeenCalledWith(null);
    expect(screen.getByRole('link', { name: 'EMS' })).toHaveAttribute('href', '/suppliers/ems');
    expect(screen.getAllByText('Doors').length).toBeGreaterThan(0);

    const down = screen.getByRole('button', { name: /\$48\.00/ });
    expect(down.className).toMatch(/cellDown/);
    expect(down.className).toMatch(/cheapest/);
    expect(down).toHaveAttribute('title', expect.stringContaining('Было $50.00 с 01.09.2026 (-4.0%)'));
    expect(screen.getByRole('button', { name: /\$49\.50/ }).className).toMatch(/cellUp/);
    expect(screen.getByRole('button', { name: /\$1\.85/ }).className).not.toMatch(/cellUp|cellDown/);
  });

  it('flags a stale supplier', async () => {
    renderPage();
    const header = (await screen.findByRole('link', { name: 'Fasteners' })).closest('th')!;
    const stale = within(header).getByText(/01\.09\.2026 · 72 дн\./);
    expect(stale.className).toMatch(/staleText/);
  });

  it('filters to changed rows and hides rows without prices', async () => {
    renderPage('/prices?changed=1');
    await screen.findByText('Door Blank 36x80');
    expect(screen.queryByText('Hinges')).not.toBeInTheDocument();
    expect(screen.queryByText('Screw')).not.toBeInTheDocument();
  });

  it('searches by name or SKU', async () => {
    renderPage();
    await screen.findByText('Door Blank 36x80');
    fireEvent.change(screen.getByLabelText('Поиск материала'), { target: { value: 'fx-1' } });
    expect(screen.getByText('Screw')).toBeInTheDocument();
    expect(screen.queryByText('Hinges')).not.toBeInTheDocument();
  });

  it('switches to date comparison and refetches with compare_to', async () => {
    renderPage();
    await screen.findByText('Door Blank 36x80');
    fireEvent.click(screen.getByRole('button', { name: 'ценой на дату' }));
    await waitFor(() =>
      expect(matrixMock).toHaveBeenLastCalledWith(expect.stringMatching(/^\d{4}-\d{2}-01$/)),
    );
    expect(screen.getByLabelText('Дата сравнения')).toBeInTheDocument();
  });

  it('opens price history with sources on cell click', async () => {
    historyMock.mockResolvedValue([
      {
        id: 'h2',
        price: 48,
        currency: 'USD',
        valid_from: '2026-11-01',
        valid_to: null,
        source: 'order',
        import_id: null,
        import_uploaded_at: null,
        order_id: 'o1',
        order_title: 'Project X — EMS',
        created_by_name: 'Мария',
        change: 'down',
      },
      {
        id: 'h1',
        price: 50,
        currency: 'USD',
        valid_from: '2026-09-01',
        valid_to: '2026-11-01',
        source: 'import',
        import_id: 'i1',
        import_uploaded_at: '2026-09-01T10:00:00Z',
        order_id: null,
        order_title: null,
        created_by_name: null,
        change: null,
      },
    ]);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /\$48\.00/ }));

    const dialog = await screen.findByRole('dialog', { name: 'История цены' });
    expect(historyMock).toHaveBeenCalledWith('door', 'ems');
    expect(await within(dialog).findByText(/прайс-лист от 01\.09\.2026/)).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Project X — EMS' })).toHaveAttribute('href', '/orders/o1');
    expect(within(dialog).getByText('активна')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
