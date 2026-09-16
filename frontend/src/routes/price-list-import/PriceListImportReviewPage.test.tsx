import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PriceListImportReviewPage } from './PriceListImportReviewPage';
import { priceListImportsApi } from '../../api/priceListImports';
import { materialsApi } from '../../api/materials';
import { categoriesApi } from '../../api/categories';
import { AuthContext } from '../../auth/AuthContext';
import type { Category, CurrentUser, PriceListEntry, PriceListImport } from '../../api/types';

vi.mock('../../api/priceListImports', () => ({
  priceListImportsApi: { upload: vi.fn(), get: vi.fn(), applyEntry: vi.fn() },
}));
vi.mock('../../api/materials', () => ({
  materialsApi: { list: vi.fn(), search: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../../api/categories', () => ({
  categoriesApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const getImportMock = vi.mocked(priceListImportsApi.get);
const applyEntryMock = vi.mocked(priceListImportsApi.applyEntry);
const materialsListMock = vi.mocked(materialsApi.list);
const categoriesListMock = vi.mocked(categoriesApi.list);

const categories: Category[] = [
  {
    id: 'cat-mesh',
    name: 'Mesh',
    sku_prefix: 'MESH',
    requires_single_supplier: true,
    next_sku_number: 58,
    created_at: '2026-01-10T12:00:00Z',
  },
];

function entryFixture(overrides: Partial<PriceListEntry> = {}): PriceListEntry {
  return {
    id: 'entry-1',
    supplier_raw_name: 'Screen mesh 18x14',
    supplier_sku: 'SKU-1',
    matched_material_id: null,
    confidence: 0.5,
    reasoning: 'Похоже на новый материал',
    price: 42,
    currency: 'USD',
    availability: null,
    min_order_qty: null,
    action: null,
    possible_duplicate_of: [],
    ...overrides,
  };
}

function renderPage(priceListImport: PriceListImport, role: CurrentUser['role'] = 'admin') {
  getImportMock.mockResolvedValue(priceListImport);
  materialsListMock.mockResolvedValue([]);
  categoriesListMock.mockResolvedValue(categories);
  return render(
    <MemoryRouter initialEntries={['/price-list-imports/import-1']}>
      <AuthContext.Provider value={{ id: 'u1', email: 'a@b.com', name: 'A', role }}>
        <Routes>
          <Route path="/price-list-imports/:importId" element={<PriceListImportReviewPage />} />
          <Route path="/suppliers" element={<div>Suppliers screen</div>} />
        </Routes>
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe('PriceListImportReviewPage', () => {
  beforeEach(() => {
    getImportMock.mockReset();
    applyEntryMock.mockReset();
    materialsListMock.mockReset();
    categoriesListMock.mockReset();
    vi.mocked(materialsApi.search).mockReset();
  });

  it('sorts rows ascending by confidence, low confidence first', async () => {
    const priceListImport: PriceListImport = {
      import_id: 'import-1',
      status: 'pending_review',
      entries: [
        entryFixture({ id: 'high', supplier_raw_name: 'High confidence row', confidence: 0.95 }),
        entryFixture({ id: 'low', supplier_raw_name: 'Low confidence row', confidence: 0.3 }),
        entryFixture({ id: 'mid', supplier_raw_name: 'Mid confidence row', confidence: 0.8 }),
      ],
    };
    renderPage(priceListImport);

    const rows = await screen.findAllByRole('row');
    const bodyRows = rows.slice(1); // skip header row
    expect(within(bodyRows[0]).getByText('Low confidence row')).toBeInTheDocument();
    expect(within(bodyRows[1]).getByText('Mid confidence row')).toBeInTheDocument();
    expect(within(bodyRows[2]).getByText('High confidence row')).toBeInTheDocument();
  });

  it('groups possible-duplicate new rows adjacently and shows the warning badge on both', async () => {
    const priceListImport: PriceListImport = {
      import_id: 'import-1',
      status: 'pending_review',
      entries: [
        entryFixture({ id: 'a', supplier_raw_name: 'Row A', confidence: 0.4, possible_duplicate_of: ['b'] }),
        entryFixture({ id: 'unrelated', supplier_raw_name: 'Unrelated row', confidence: 0.5 }),
        entryFixture({ id: 'b', supplier_raw_name: 'Row B', confidence: 0.6, possible_duplicate_of: ['a'] }),
      ],
    };
    renderPage(priceListImport);

    const rows = await screen.findAllByRole('row');
    const bodyRows = rows.slice(1);
    // Row A (lowest confidence) placed first, its duplicate Row B pulled up
    // to sit immediately after it, ahead of the unrelated row.
    expect(within(bodyRows[0]).getByText('Row A')).toBeInTheDocument();
    expect(within(bodyRows[1]).getByText('Row B')).toBeInTheDocument();
    expect(within(bodyRows[2]).getByText('Unrelated row')).toBeInTheDocument();

    expect(within(bodyRows[0]).getByText(/похоже на ту же позицию каталога/)).toBeInTheDocument();
    expect(within(bodyRows[1]).getByText(/похоже на ту же позицию каталога/)).toBeInTheDocument();
    expect(within(bodyRows[2]).queryByText(/похоже на ту же позицию каталога/)).not.toBeInTheDocument();
  });

  it('applies all checked pending rows and reports a summary', async () => {
    const user = userEvent.setup();
    const priceListImport: PriceListImport = {
      import_id: 'import-1',
      status: 'pending_review',
      entries: [
        entryFixture({ id: 'a', confidence: 0.4 }),
        entryFixture({ id: 'b', confidence: 0.6, supplier_raw_name: 'Second row' }),
      ],
    };
    applyEntryMock.mockImplementation((_importId, entryId) =>
      Promise.resolve(entryFixture({ id: entryId, action: 'new' })),
    );
    renderPage(priceListImport);

    await screen.findByText('Screen mesh 18x14');

    const categorySelects = await screen.findAllByLabelText(/категория/i);
    for (const select of categorySelects) {
      await user.selectOptions(select, 'cat-mesh');
    }

    const applyButton = screen.getByRole('button', { name: /Применить выбранные/ });
    await user.click(applyButton);

    await waitFor(() => expect(applyEntryMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('Применено 2 из 2')).toBeInTheDocument();
  });

  it('excludes a skipped row from the bulk-apply set without applying it', async () => {
    const user = userEvent.setup();
    const priceListImport: PriceListImport = {
      import_id: 'import-1',
      status: 'pending_review',
      entries: [
        entryFixture({ id: 'a', confidence: 0.4 }),
        entryFixture({ id: 'b', confidence: 0.6, supplier_raw_name: 'Second row' }),
      ],
    };
    applyEntryMock.mockImplementation((_importId, entryId, payload) =>
      Promise.resolve(
        entryFixture({ id: entryId, action: payload.action === 'skip' ? 'skip' : 'new' }),
      ),
    );

    materialsListMock.mockResolvedValue([]);
    categoriesListMock.mockResolvedValue(categories);
    let getCallCount = 0;
    getImportMock.mockImplementation(() => {
      getCallCount += 1;
      if (getCallCount === 1) return Promise.resolve(priceListImport);
      return Promise.resolve({
        ...priceListImport,
        entries: [
          entryFixture({ id: 'a', confidence: 0.4, action: 'skip' }),
          entryFixture({ id: 'b', confidence: 0.6, supplier_raw_name: 'Second row' }),
        ],
      });
    });

    render(
      <MemoryRouter initialEntries={['/price-list-imports/import-1']}>
        <AuthContext.Provider value={{ id: 'u1', email: 'a@b.com', name: 'A', role: 'admin' }}>
          <Routes>
            <Route path="/price-list-imports/:importId" element={<PriceListImportReviewPage />} />
          </Routes>
        </AuthContext.Provider>
      </MemoryRouter>,
    );

    await screen.findByText('Screen mesh 18x14');
    const skipButtons = screen.getAllByRole('button', { name: /Пропустить/ });
    await user.click(skipButtons[0]);

    await waitFor(() =>
      expect(applyEntryMock).toHaveBeenCalledWith('import-1', 'a', { action: 'skip' }),
    );

    await screen.findByText('Пропущено');

    await user.selectOptions(screen.getByLabelText(/категория/i), 'cat-mesh');

    const applyButton = screen.getByRole('button', { name: /Применить выбранные/ });
    await user.click(applyButton);

    await waitFor(() => expect(applyEntryMock).toHaveBeenCalledTimes(2)); // 1 skip + 1 apply for row b
    expect(applyEntryMock).not.toHaveBeenCalledWith('import-1', 'a', expect.objectContaining({ action: 'new' }));
  });

  it('creates a new material from an unmatched row via category select, without any manual SKU input (ADR-0034 §7)', async () => {
    const user = userEvent.setup();
    const priceListImport: PriceListImport = {
      import_id: 'import-1',
      status: 'pending_review',
      entries: [entryFixture({ id: 'a', confidence: 0.4 })],
    };
    applyEntryMock.mockResolvedValue(entryFixture({ id: 'a', action: 'new' }));
    renderPage(priceListImport);

    await screen.findByText('Screen mesh 18x14');

    expect(screen.queryByLabelText(/sku/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/internal_sku/i)).not.toBeInTheDocument();

    await user.selectOptions(await screen.findByLabelText(/категория/i), 'cat-mesh');

    const applyButton = screen.getByRole('button', { name: /Применить выбранные/ });
    await user.click(applyButton);

    await waitFor(() =>
      expect(applyEntryMock).toHaveBeenCalledWith('import-1', 'a', {
        action: 'new',
        category_id: 'cat-mesh',
        canonical_name: 'Screen mesh 18x14',
      }),
    );
  });

  describe('admin-only actions (ADR-0024 §7 — UI convenience only)', () => {
    function pendingImport(): PriceListImport {
      return {
        import_id: 'import-1',
        status: 'pending_review',
        entries: [entryFixture({ id: 'a' })],
      };
    }

    it('disables apply/skip actions for employee role', async () => {
      renderPage(pendingImport(), 'employee');

      await screen.findByText('Screen mesh 18x14');

      expect(screen.getByRole('button', { name: /Применить выбранные/ })).toBeDisabled();
      expect(screen.getByRole('button', { name: /Пропустить/ })).toBeDisabled();
    });

    it('enables apply/skip actions for admin role', async () => {
      renderPage(pendingImport(), 'admin');

      await screen.findByText('Screen mesh 18x14');

      expect(screen.getByRole('button', { name: /Применить выбранные/ })).toBeEnabled();
      expect(screen.getByRole('button', { name: /Пропустить/ })).toBeEnabled();
    });
  });
});
