import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AllocationResultPage } from './AllocationResultPage';
import { allocationApi } from '../api/allocation';
import { materialsApi } from '../api/materials';
import { pricesApi } from '../api/prices';
import { projectsApi } from '../api/projects';
import { suppliersApi } from '../api/suppliers';
import type { AllocationRun, Material, Price, Project, Supplier } from '../api/types';

vi.mock('../api/allocation', () => ({
  allocationApi: { run: vi.fn(), get: vi.fn() },
}));
vi.mock('../api/projects', () => ({
  projectsApi: { create: vi.fn(), get: vi.fn(), addItem: vi.fn() },
}));
vi.mock('../api/suppliers', () => ({
  suppliersApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../api/materials', () => ({
  materialsApi: { list: vi.fn(), search: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../api/prices', () => ({
  pricesApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const runMock = vi.mocked(allocationApi.run);
const projectGetMock = vi.mocked(projectsApi.get);
const suppliersListMock = vi.mocked(suppliersApi.list);
const materialsListMock = vi.mocked(materialsApi.list);
const pricesListMock = vi.mocked(pricesApi.list);

const project: Project & { items: []; latest_allocation_run: null } = {
  id: 'proj-1',
  title: 'Pool cage — Bayshore Rd',
  created_by: null,
  status: 'draft',
  created_at: '2026-08-17T00:00:00Z',
  items: [],
  latest_allocation_run: null,
};

const supplierA: Supplier = {
  id: 'sup-a',
  name: 'ABC Supply',
  contacts: null,
  currency: 'USD',
  delivery_policy: { flat_fee: 25, free_shipping_threshold: 500, per_order_min_amount: 0, lead_time_days: 3 },
};

const supplierB: Supplier = {
  id: 'sup-b',
  name: 'Screenmobile Wholesale',
  contacts: null,
  currency: 'USD',
  delivery_policy: { flat_fee: 15, free_shipping_threshold: null, per_order_min_amount: 0, lead_time_days: 5 },
};

const materialScreen: Material = {
  id: 'mat-1',
  internal_sku: 'MSH-FG-1814',
  canonical_name: 'Сетка Fiberglass 18x14',
  category: 'Сетка',
  unit: 'рулон',
  attributes: {},
};

function renderPage(projectId = 'proj-1') {
  return render(
    <MemoryRouter initialEntries={[`/projects/${projectId}/allocation`]}>
      <Routes>
        <Route path="/projects/:projectId" element={<div>Project detail screen</div>} />
        <Route path="/projects/:projectId/allocation" element={<AllocationResultPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('AllocationResultPage', () => {
  beforeEach(() => {
    runMock.mockReset();
    projectGetMock.mockReset();
    suppliersListMock.mockReset();
    materialsListMock.mockReset();
    pricesListMock.mockReset();

    projectGetMock.mockResolvedValue(project);
    suppliersListMock.mockResolvedValue([supplierA, supplierB]);
    materialsListMock.mockResolvedValue([materialScreen]);
    pricesListMock.mockResolvedValue([]);
  });

  it('shows an explicit message and no supplier cards when status is infeasible', async () => {
    const infeasibleRun: AllocationRun = {
      id: 'run-1',
      project_id: 'proj-1',
      created_at: '2026-08-17T00:00:00Z',
      algorithm_version: 'v1',
      status: 'infeasible',
      lines: [],
      orphaned_materials: [],
      supplier_summaries: [],
    };
    runMock.mockResolvedValue(infeasibleRun);

    renderPage();

    expect(await screen.findByText(/Не удалось построить план закупки/)).toBeInTheDocument();
    expect(screen.queryByText(supplierA.name)).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Назад к проекту/ }));
    expect(await screen.findByText('Project detail screen')).toBeInTheDocument();
  });

  it('renders supplier cards, totals and orphaned materials when status is ok', async () => {
    const okRun: AllocationRun = {
      id: 'run-2',
      project_id: 'proj-1',
      created_at: '2026-08-17T00:00:00Z',
      algorithm_version: 'v1',
      status: 'ok',
      lines: [
        {
          id: 'line-1',
          material_id: 'mat-1',
          supplier_id: 'sup-a',
          quantity: 10,
          unit_price: 12,
          line_total: 120,
        },
      ],
      orphaned_materials: [
        { material_id: 'mat-1', required_quantity: 5, best_partial_supplier_id: null, best_partial_available: null },
      ],
      supplier_summaries: [
        { supplier_id: 'sup-a', goods_total: 120, delivery_fee: 0, free_shipping_achieved: true },
      ],
    };
    runMock.mockResolvedValue(okRun);
    pricesListMock.mockResolvedValue([
      { id: 'p1', material_id: 'mat-1', supplier_id: 'sup-a', price: 12, currency: 'USD', availability: 100, min_order_qty: null, valid_from: '2026-01-01', valid_to: null, source_import_id: null },
    ] satisfies Price[]);

    renderPage();

    expect(await screen.findByText(supplierA.name)).toBeInTheDocument();
    expect(screen.getAllByText(materialScreen.canonical_name).length).toBeGreaterThan(0);
    expect(screen.getByText(/Подтвердить и создать ордера/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Подтвердить и создать ордера/ })).toBeDisabled();
    expect(screen.getByText(/Не удалось разместить/i)).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Назад к проекту/ }));
    expect(await screen.findByText('Project detail screen')).toBeInTheDocument();
  });
});
