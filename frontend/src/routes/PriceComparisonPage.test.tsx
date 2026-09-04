import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PriceComparisonPage } from './PriceComparisonPage';
import { materialsApi } from '../api/materials';
import { priceComparisonApi } from '../api/priceComparison';
import { projectsApi } from '../api/projects';
import { suppliersApi } from '../api/suppliers';
import type { Material, MaterialComparisonRow, ProjectWithItems, Supplier } from '../api/types';

vi.mock('../api/priceComparison', () => ({
  priceComparisonApi: { get: vi.fn() },
}));
vi.mock('../api/projects', () => ({
  projectsApi: {
    get: vi.fn(),
    list: vi.fn(),
    create: vi.fn(),
    updateProject: vi.fn(),
    addItem: vi.fn(),
    updateItem: vi.fn(),
    removeItem: vi.fn(),
    remove: vi.fn(),
    complete: vi.fn(),
  },
}));
vi.mock('../api/materials', () => ({
  materialsApi: { list: vi.fn(), search: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../api/suppliers', () => ({
  suppliersApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    createOffice: vi.fn(),
    updateOffice: vi.fn(),
    removeOffice: vi.fn(),
    createContact: vi.fn(),
    updateContact: vi.fn(),
    removeContact: vi.fn(),
  },
}));

const getComparisonMock = vi.mocked(priceComparisonApi.get);
const getProjectMock = vi.mocked(projectsApi.get);
const materialsListMock = vi.mocked(materialsApi.list);
const suppliersListMock = vi.mocked(suppliersApi.list);

function supplierFixture(overrides: Partial<Supplier> = {}): Supplier {
  return {
    id: 'sup-a',
    name: 'ABC Supply',
    short_name: null,
    contacts: null,
    currency: 'USD',
    delivery_policy: { flat_fee: 0, free_shipping_threshold: null, per_order_min_amount: 0, lead_time_days: 0 },
    website: null,
    region: null,
    catalog_link: null,
    status: null,
    payment_terms: null,
    portal_url: null,
    comments: null,
    ...overrides,
  };
}

const material: Material = {
  id: 'mat-1',
  internal_sku: 'MSH-FG-1814',
  canonical_name: 'Сетка Fiberglass 18x14',
  category: 'Сетка',
  unit: 'рулон',
  attributes: {},
};

function projectFixture(overrides: Partial<ProjectWithItems> = {}): ProjectWithItems {
  return {
    id: 'proj-1',
    title: 'Проект #20675',
    status: 'calculated',
    created_at: '2026-08-01T00:00:00Z',
    items: [{ id: 'item-1', project_id: 'proj-1', material_id: 'mat-1', quantity: 10 }],
    latest_allocation_run: null,
    ...overrides,
  } as ProjectWithItems;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/projects/proj-1/comparison']}>
      <Routes>
        <Route path="/projects/:projectId/comparison" element={<PriceComparisonPage />} />
        <Route path="/projects/:projectId" element={<div>Project detail screen</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('PriceComparisonPage', () => {
  beforeEach(() => {
    getComparisonMock.mockReset();
    getProjectMock.mockReset();
    materialsListMock.mockReset();
    suppliersListMock.mockReset();
    getProjectMock.mockResolvedValue(projectFixture());
    materialsListMock.mockResolvedValue([material]);
    suppliersListMock.mockResolvedValue([]);
  });

  it('shows a dash for a supplier with no plan price on a material', async () => {
    const rows: MaterialComparisonRow[] = [
      {
        project_item_id: 'item-1',
        material_id: 'mat-1',
        plan: [
          { supplier_id: 'sup-a', supplier_name: 'ABC Supply', price: 25, availability: 50, is_cheapest: true },
        ],
        supplier_responses: [],
      },
    ];
    getComparisonMock.mockResolvedValue({ rows });

    renderPage();

    expect(await screen.findByText(material.canonical_name)).toBeInTheDocument();
    expect(screen.getByText('$25.00')).toBeInTheDocument();
  });

  it('highlights the is_cheapest plan cell', async () => {
    const rows: MaterialComparisonRow[] = [
      {
        project_item_id: 'item-1',
        material_id: 'mat-1',
        plan: [
          { supplier_id: 'sup-a', supplier_name: 'ABC Supply', price: 25, availability: 50, is_cheapest: true },
          { supplier_id: 'sup-b', supplier_name: 'Better Supply', price: 30, availability: 50, is_cheapest: false },
        ],
        supplier_responses: [],
      },
    ];
    getComparisonMock.mockResolvedValue({ rows });

    renderPage();

    const cheapestCell = await screen.findByText('$25.00');
    expect(cheapestCell.closest('td')?.className).toMatch(/cheapest/);
    const otherCell = screen.getByText('$30.00');
    expect(otherCell.closest('td')?.className).not.toMatch(/cheapest/);
  });

  it('shows an availability warning on the cheapest plan cell when availability is short', async () => {
    const rows: MaterialComparisonRow[] = [
      {
        project_item_id: 'item-1',
        material_id: 'mat-1',
        plan: [
          { supplier_id: 'sup-a', supplier_name: 'ABC Supply', price: 25, availability: 3, is_cheapest: true },
        ],
        supplier_responses: [],
      },
    ];
    getComparisonMock.mockResolvedValue({ rows });

    renderPage();

    expect(await screen.findByText(/у поставщика доступно 3 рулон, требуется 10/)).toBeInTheDocument();
  });

  it('shows a dash for a supplier response with neither received_price nor confirmed_price set', async () => {
    const rows: MaterialComparisonRow[] = [
      {
        project_item_id: 'item-1',
        material_id: 'mat-1',
        plan: [],
        supplier_responses: [
          {
            supplier_id: 'sup-a',
            supplier_name: 'ABC Supply',
            quoted_price: 25,
            received_price: null,
            confirmed_price: null,
            declined_at: null,
            decline_reason: null,
            is_cheapest: true,
          },
        ],
      },
    ];
    getComparisonMock.mockResolvedValue({ rows });

    renderPage();

    await screen.findByText(material.canonical_name);
    // No answer yet from the supplier — quoted_price (the plan) is not shown
    // here, that's what the "План" table is for.
    expect(screen.queryByText('$25.00')).not.toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('shows "Получена" as the price source tooltip when received_price is set but not confirmed', async () => {
    const rows: MaterialComparisonRow[] = [
      {
        project_item_id: 'item-1',
        material_id: 'mat-1',
        plan: [],
        supplier_responses: [
          {
            supplier_id: 'sup-a',
            supplier_name: 'ABC Supply',
            quoted_price: 25,
            received_price: 23.5,
            confirmed_price: null,
            declined_at: null,
            decline_reason: null,
            is_cheapest: true,
          },
        ],
      },
    ];
    getComparisonMock.mockResolvedValue({ rows });

    renderPage();

    const cell = await screen.findByText('$23.50');
    expect(cell).toHaveAttribute('title', 'Получена');
  });

  it('shows "Подтверждена" as the price source tooltip when confirmed_price is set', async () => {
    const rows: MaterialComparisonRow[] = [
      {
        project_item_id: 'item-1',
        material_id: 'mat-1',
        plan: [],
        supplier_responses: [
          {
            supplier_id: 'sup-a',
            supplier_name: 'ABC Supply',
            quoted_price: 25,
            received_price: 23.5,
            confirmed_price: 24,
            declined_at: null,
            decline_reason: null,
            is_cheapest: true,
          },
        ],
      },
    ];
    getComparisonMock.mockResolvedValue({ rows });

    renderPage();

    const cell = await screen.findByText('$24.00');
    expect(cell).toHaveAttribute('title', 'Подтверждена');
  });

  it('shows the full supplier name as a tooltip in the "Ответы поставщиков" column header', async () => {
    const rows: MaterialComparisonRow[] = [
      {
        project_item_id: 'item-1',
        material_id: 'mat-1',
        plan: [],
        supplier_responses: [
          {
            supplier_id: 'sup-a',
            supplier_name: 'Aluminum Distributors Int LLC',
            quoted_price: 25,
            received_price: null,
            confirmed_price: null,
            declined_at: null,
            decline_reason: null,
            is_cheapest: true,
          },
        ],
      },
    ];
    getComparisonMock.mockResolvedValue({ rows });
    suppliersListMock.mockResolvedValue([
      supplierFixture({ id: 'sup-a', name: 'Aluminum Distributors Int LLC', short_name: 'ADI LLC' }),
    ]);

    renderPage();

    const header = await screen.findByText('ADI LLC', { selector: 'th' });
    expect(header).toHaveAttribute('title', 'Aluminum Distributors Int LLC');
  });

  it('shows a struck-through received price next to "Отказался" for a declined response', async () => {
    const rows: MaterialComparisonRow[] = [
      {
        project_item_id: 'item-1',
        material_id: 'mat-1',
        plan: [],
        supplier_responses: [
          {
            supplier_id: 'sup-a',
            supplier_name: 'ABC Supply',
            quoted_price: 25,
            received_price: 23.5,
            confirmed_price: null,
            declined_at: '2026-08-18T10:00:00Z',
            decline_reason: 'нет в наличии',
            is_cheapest: false,
          },
        ],
      },
    ];
    getComparisonMock.mockResolvedValue({ rows });

    renderPage();

    expect(await screen.findByText('Отказался')).toBeInTheDocument();
    expect(screen.getByText('$23.50')).toBeInTheDocument();
  });

  it('uses short_name in the column header when set, with the full name as a tooltip', async () => {
    const rows: MaterialComparisonRow[] = [
      {
        project_item_id: 'item-1',
        material_id: 'mat-1',
        plan: [
          {
            supplier_id: 'sup-a',
            supplier_name: 'Aluminum Distributors Int LLC',
            price: 25,
            availability: 50,
            is_cheapest: true,
          },
        ],
        supplier_responses: [],
      },
    ];
    getComparisonMock.mockResolvedValue({ rows });
    suppliersListMock.mockResolvedValue([
      supplierFixture({
        id: 'sup-a',
        name: 'Aluminum Distributors Int LLC',
        short_name: 'ADI LLC',
      }),
    ]);

    renderPage();

    const header = await screen.findByText('ADI LLC');
    expect(header.tagName).toBe('TH');
    expect(header).toHaveAttribute('title', 'Aluminum Distributors Int LLC');
    expect(screen.queryByText('Aluminum Distributors Int LLC')).not.toBeInTheDocument();
  });

  it('falls back to the full supplier name in the column header when short_name is not set', async () => {
    const rows: MaterialComparisonRow[] = [
      {
        project_item_id: 'item-1',
        material_id: 'mat-1',
        plan: [
          { supplier_id: 'sup-a', supplier_name: 'ABC Supply', price: 25, availability: 50, is_cheapest: true },
        ],
        supplier_responses: [],
      },
    ];
    getComparisonMock.mockResolvedValue({ rows });
    suppliersListMock.mockResolvedValue([supplierFixture({ short_name: null })]);

    renderPage();

    const header = await screen.findByText('ABC Supply', { selector: 'th' });
    expect(header).toHaveAttribute('title', 'ABC Supply');
  });

  it('shows the empty state for supplier responses when the project has no Order', async () => {
    const rows: MaterialComparisonRow[] = [
      {
        project_item_id: 'item-1',
        material_id: 'mat-1',
        plan: [
          { supplier_id: 'sup-a', supplier_name: 'ABC Supply', price: 25, availability: 50, is_cheapest: true },
        ],
        supplier_responses: [],
      },
    ];
    getComparisonMock.mockResolvedValue({ rows });

    renderPage();

    expect(
      await screen.findByText(/Ордера ещё не созданы — сравнение по факту появится после отправки/),
    ).toBeInTheDocument();
  });
});
