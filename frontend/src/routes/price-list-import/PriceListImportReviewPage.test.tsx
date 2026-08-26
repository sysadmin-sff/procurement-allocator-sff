import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PriceListImportReviewPage } from './PriceListImportReviewPage';
import { priceListImportsApi } from '../../api/priceListImports';
import { materialsApi } from '../../api/materials';
import { AuthContext } from '../../auth/AuthContext';
import type { CurrentUser, PriceListEntry, PriceListImport } from '../../api/types';

vi.mock('../../api/priceListImports', () => ({
  priceListImportsApi: { upload: vi.fn(), get: vi.fn(), applyEntry: vi.fn() },
}));
vi.mock('../../api/materials', () => ({
  materialsApi: { list: vi.fn(), search: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const getImportMock = vi.mocked(priceListImportsApi.get);
const applyEntryMock = vi.mocked(priceListImportsApi.applyEntry);
const materialsListMock = vi.mocked(materialsApi.list);

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
    suggested_internal_sku: 'MSH-NEW-1',
    possible_duplicate_of: [],
    ...overrides,
  };
}

function renderPage(priceListImport: PriceListImport, role: CurrentUser['role'] = 'admin') {
  getImportMock.mockResolvedValue(priceListImport);
  materialsListMock.mockResolvedValue([]);
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

    expect(within(bodyRows[0]).getByText(/похоже на другую новую позицию/)).toBeInTheDocument();
    expect(within(bodyRows[1]).getByText(/похоже на другую новую позицию/)).toBeInTheDocument();
    expect(within(bodyRows[2]).queryByText(/похоже на другую новую позицию/)).not.toBeInTheDocument();
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

    const applyButton = screen.getByRole('button', { name: /Применить выбранные/ });
    await user.click(applyButton);

    await waitFor(() => expect(applyEntryMock).toHaveBeenCalledTimes(2)); // 1 skip + 1 apply for row b
    expect(applyEntryMock).not.toHaveBeenCalledWith('import-1', 'a', expect.objectContaining({ action: 'new' }));
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
