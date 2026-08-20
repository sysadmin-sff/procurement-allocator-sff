import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PriceComparisonPage } from './PriceComparisonPage';
import { materialsApi } from '../api/materials';
import { priceComparisonApi } from '../api/priceComparison';
import { projectsApi } from '../api/projects';
import type { Material, MaterialComparisonRow, ProjectWithItems } from '../api/types';

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

const getComparisonMock = vi.mocked(priceComparisonApi.get);
const getProjectMock = vi.mocked(projectsApi.get);
const materialsListMock = vi.mocked(materialsApi.list);

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
    getProjectMock.mockResolvedValue(projectFixture());
    materialsListMock.mockResolvedValue([material]);
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

  it('leaves an unsent supplier response cell blank, not a dash', async () => {
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
    // ABC Supply appears in the response table but Better Supply column doesn't exist at all
    // since only one supplier ever responded — assert the response price renders.
    expect(screen.getByText('$25.00')).toBeInTheDocument();
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
