import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AllocationResultPage } from './AllocationResultPage';
import { allocationApi } from '../api/allocation';
import { ApiError } from '../api/client';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import { pricesApi } from '../api/prices';
import { projectsApi } from '../api/projects';
import { suppliersApi } from '../api/suppliers';
import type {
  AllocationRun,
  Material,
  OrderDraftConflict,
  Price,
  Project,
  Supplier,
} from '../api/types';

vi.mock('../api/allocation', () => ({
  allocationApi: { run: vi.fn(), get: vi.fn(), overrideLine: vi.fn() },
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
vi.mock('../api/orders', () => ({
  ordersApi: {
    createForRun: vi.fn(),
    listForProject: vi.fn(),
    get: vi.fn(),
    setConfirmedPrice: vi.fn(),
  },
}));

const runMock = vi.mocked(allocationApi.run);
const getRunMock = vi.mocked(allocationApi.get);
const overrideLineMock = vi.mocked(allocationApi.overrideLine);
const projectGetMock = vi.mocked(projectsApi.get);
const suppliersListMock = vi.mocked(suppliersApi.list);
const materialsListMock = vi.mocked(materialsApi.list);
const pricesListMock = vi.mocked(pricesApi.list);
const createOrdersMock = vi.mocked(ordersApi.createForRun);

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
  short_name: null,
  contacts: null,
  currency: 'USD',
  delivery_policy: { flat_fee: 25, free_shipping_threshold: 500, per_order_min_amount: 0, lead_time_days: 3 },
  website: null,
  region: null,
  catalog_link: null,
  status: null,
  payment_terms: null,
  portal_url: null,
  comments: null,
};

const supplierB: Supplier = {
  id: 'sup-b',
  name: 'Screenmobile Wholesale',
  short_name: null,
  contacts: null,
  currency: 'USD',
  delivery_policy: { flat_fee: 15, free_shipping_threshold: null, per_order_min_amount: 0, lead_time_days: 5 },
  website: null,
  region: null,
  catalog_link: null,
  status: null,
  payment_terms: null,
  portal_url: null,
  comments: null,
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
    getRunMock.mockReset();
    overrideLineMock.mockReset();
    projectGetMock.mockReset();
    suppliersListMock.mockReset();
    materialsListMock.mockReset();
    pricesListMock.mockReset();
    createOrdersMock.mockReset();

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
          overridden_at: null,
          original_supplier_id: null,
          original_unit_price: null,
          ordered_at: null,
        },
      ],
      orphaned_materials: [
        { material_id: 'mat-1', required_quantity: 5, best_partial_supplier_id: null, best_partial_available: null },
      ],
      supplier_summaries: [
        {
          supplier_id: 'sup-a',
          goods_total: 120,
          delivery_fee: 0,
          free_shipping_achieved: true,
          below_min_order: false,
        },
      ],
    };
    runMock.mockResolvedValue(okRun);
    pricesListMock.mockResolvedValue([
      { id: 'p1', material_id: 'mat-1', supplier_id: 'sup-a', price: 12, currency: 'USD', availability: 100, min_order_qty: null, valid_from: '2026-01-01', valid_to: null, source_import_id: null },
    ] satisfies Price[]);

    renderPage();

    expect(await screen.findByText(supplierA.name)).toBeInTheDocument();
    expect(screen.getAllByText(materialScreen.canonical_name).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /Подтвердить и создать ордера/ })).toBeEnabled();
    expect(screen.getByText(/Не удалось разместить/i)).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Назад к проекту/ }));
    expect(await screen.findByText('Project detail screen')).toBeInTheDocument();
  });

  it('overrides the supplier on a line via the select, then refetches the run', async () => {
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
          overridden_at: null,
          original_supplier_id: null,
          original_unit_price: null,
          ordered_at: null,
        },
      ],
      orphaned_materials: [],
      supplier_summaries: [
        {
          supplier_id: 'sup-a',
          goods_total: 120,
          delivery_fee: 0,
          free_shipping_achieved: true,
          below_min_order: false,
        },
      ],
    };
    const refetchedRun: AllocationRun = {
      ...okRun,
      lines: [
        {
          id: 'line-1',
          material_id: 'mat-1',
          supplier_id: 'sup-b',
          quantity: 10,
          unit_price: 15,
          line_total: 150,
          overridden_at: '2026-08-18T00:00:00Z',
          original_supplier_id: 'sup-a',
          original_unit_price: 12,
          ordered_at: null,
        },
      ],
      supplier_summaries: [
        {
          supplier_id: 'sup-b',
          goods_total: 150,
          delivery_fee: 15,
          free_shipping_achieved: false,
          below_min_order: false,
        },
      ],
    };
    runMock.mockResolvedValue(okRun);
    getRunMock.mockResolvedValue(refetchedRun);
    overrideLineMock.mockResolvedValue(refetchedRun.lines[0]);
    pricesListMock.mockResolvedValue([
      { id: 'p1', material_id: 'mat-1', supplier_id: 'sup-a', price: 12, currency: 'USD', availability: 100, min_order_qty: null, valid_from: '2026-01-01', valid_to: null, source_import_id: null },
      { id: 'p2', material_id: 'mat-1', supplier_id: 'sup-b', price: 15, currency: 'USD', availability: 100, min_order_qty: null, valid_from: '2026-01-01', valid_to: null, source_import_id: null },
    ] satisfies Price[]);

    renderPage();

    const select = await screen.findByRole('combobox');
    const user = userEvent.setup();
    await user.selectOptions(select, 'sup-b');

    expect(overrideLineMock).toHaveBeenCalledWith('proj-1', 'run-2', 'line-1', 'sup-b');
    expect(await screen.findByText(supplierB.name)).toBeInTheDocument();
    // Two indicators are expected: the supplier card header shows "изменено
    // вручную" whenever any of its lines were overridden, and the line
    // itself carries the same badge plus the "было: …" detail.
    expect(screen.getAllByText(/изменено вручную/)).toHaveLength(2);
    expect(screen.getByText(/было: ABC Supply, \$12\.00\/ед\./)).toBeInTheDocument();
  });

  it('shows a below-min-order notice row under the supplier header', async () => {
    const okRun: AllocationRun = {
      id: 'run-3',
      project_id: 'proj-1',
      created_at: '2026-08-17T00:00:00Z',
      algorithm_version: 'v1',
      status: 'ok',
      lines: [
        {
          id: 'line-1',
          material_id: 'mat-1',
          supplier_id: 'sup-a',
          quantity: 1,
          unit_price: 12,
          line_total: 12,
          overridden_at: '2026-08-18T00:00:00Z',
          original_supplier_id: 'sup-b',
          original_unit_price: 15,
          ordered_at: null,
        },
      ],
      orphaned_materials: [],
      supplier_summaries: [
        {
          supplier_id: 'sup-a',
          goods_total: 12,
          delivery_fee: 25,
          free_shipping_achieved: false,
          below_min_order: true,
        },
      ],
    };
    runMock.mockResolvedValue(okRun);
    pricesListMock.mockResolvedValue([
      { id: 'p1', material_id: 'mat-1', supplier_id: 'sup-a', price: 12, currency: 'USD', availability: 100, min_order_qty: null, valid_from: '2026-01-01', valid_to: null, source_import_id: null },
    ] satisfies Price[]);

    renderPage();

    expect(await screen.findByText(/Сумма заказа \$12\.00 меньше минимальной/)).toBeInTheDocument();
  });

  it('creates orders and navigates to the project on click', async () => {
    const okRun: AllocationRun = {
      id: 'run-4',
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
          overridden_at: null,
          original_supplier_id: null,
          original_unit_price: null,
          ordered_at: null,
        },
      ],
      orphaned_materials: [],
      supplier_summaries: [
        {
          supplier_id: 'sup-a',
          goods_total: 120,
          delivery_fee: 0,
          free_shipping_achieved: true,
          below_min_order: false,
        },
      ],
    };
    runMock.mockResolvedValue(okRun);
    pricesListMock.mockResolvedValue([
      { id: 'p1', material_id: 'mat-1', supplier_id: 'sup-a', price: 12, currency: 'USD', availability: 100, min_order_qty: null, valid_from: '2026-01-01', valid_to: null, source_import_id: null },
    ] satisfies Price[]);
    createOrdersMock.mockResolvedValue([]);

    renderPage();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Подтвердить и создать ордера/ }));

    expect(createOrdersMock).toHaveBeenCalledWith('proj-1', 'run-4', undefined);
    expect(await screen.findByText('Project detail screen')).toBeInTheDocument();
  });

  it('opens the conflict modal instead of an error banner on 409, and lists the conflicting suppliers', async () => {
    const okRun: AllocationRun = {
      id: 'run-7',
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
          overridden_at: null,
          original_supplier_id: null,
          original_unit_price: null,
          ordered_at: null,
        },
      ],
      orphaned_materials: [],
      supplier_summaries: [
        {
          supplier_id: 'sup-a',
          goods_total: 120,
          delivery_fee: 0,
          free_shipping_achieved: true,
          below_min_order: false,
        },
      ],
    };
    runMock.mockResolvedValue(okRun);
    pricesListMock.mockResolvedValue([
      { id: 'p1', material_id: 'mat-1', supplier_id: 'sup-a', price: 12, currency: 'USD', availability: 100, min_order_qty: null, valid_from: '2026-01-01', valid_to: null, source_import_id: null },
    ] satisfies Price[]);
    const conflict: OrderDraftConflict = {
      detail: 'draft_orders_exist',
      suppliers_with_existing_drafts: [
        {
          supplier_id: 'sup-a',
          supplier_name: 'ABC Supply',
          existing_draft_orders: [
            { order_id: 'ord-1', total_amount: 120, has_confirmed_prices: false },
            { order_id: 'ord-2', total_amount: 120, has_confirmed_prices: false },
          ],
        },
      ],
    };
    createOrdersMock.mockRejectedValueOnce(new ApiError(409, conflict));

    renderPage();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Подтвердить и создать ордера/ }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getAllByText('$120.00')).toHaveLength(2);
    // Not shown as a generic error banner alongside the modal.
    expect(document.querySelectorAll('[class*="banner"]')).toHaveLength(0);
  });

  it('replaces drafts when the modal\'s "Заменить черновики" is confirmed, then navigates', async () => {
    const okRun: AllocationRun = {
      id: 'run-8',
      project_id: 'proj-1',
      created_at: '2026-08-17T00:00:00Z',
      algorithm_version: 'v1',
      status: 'ok',
      lines: [],
      orphaned_materials: [],
      supplier_summaries: [
        {
          supplier_id: 'sup-a',
          goods_total: 120,
          delivery_fee: 0,
          free_shipping_achieved: true,
          below_min_order: false,
        },
      ],
    };
    runMock.mockResolvedValue(okRun);
    pricesListMock.mockResolvedValue([]);
    const conflict: OrderDraftConflict = {
      detail: 'draft_orders_exist',
      suppliers_with_existing_drafts: [
        {
          supplier_id: 'sup-a',
          supplier_name: 'ABC Supply',
          existing_draft_orders: [
            { order_id: 'ord-1', total_amount: 120, has_confirmed_prices: false },
          ],
        },
      ],
    };
    createOrdersMock.mockRejectedValueOnce(new ApiError(409, conflict));
    createOrdersMock.mockResolvedValueOnce([]);

    renderPage();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Подтвердить и создать ордера/ }));
    await screen.findByRole('dialog');
    await user.click(screen.getByRole('button', { name: /Заменить черновики/ }));

    expect(createOrdersMock).toHaveBeenCalledTimes(2);
    expect(createOrdersMock).toHaveBeenNthCalledWith(2, 'proj-1', 'run-8', true);
    expect(await screen.findByText('Project detail screen')).toBeInTheDocument();
  });

  it('does not offer an "add additional" action on the page — the backend has no way to fulfill it', async () => {
    const okRun: AllocationRun = {
      id: 'run-9',
      project_id: 'proj-1',
      created_at: '2026-08-17T00:00:00Z',
      algorithm_version: 'v1',
      status: 'ok',
      lines: [],
      orphaned_materials: [],
      supplier_summaries: [
        {
          supplier_id: 'sup-a',
          goods_total: 120,
          delivery_fee: 0,
          free_shipping_achieved: true,
          below_min_order: false,
        },
      ],
    };
    runMock.mockResolvedValue(okRun);
    pricesListMock.mockResolvedValue([]);
    const conflict: OrderDraftConflict = {
      detail: 'draft_orders_exist',
      suppliers_with_existing_drafts: [
        {
          supplier_id: 'sup-a',
          supplier_name: 'ABC Supply',
          existing_draft_orders: [
            { order_id: 'ord-1', total_amount: 120, has_confirmed_prices: false },
          ],
        },
      ],
    };
    createOrdersMock.mockRejectedValueOnce(new ApiError(409, conflict));

    renderPage();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Подтвердить и создать ордера/ }));
    await screen.findByRole('dialog');

    expect(
      screen.queryByRole('button', { name: /Создать дополнительно/ }),
    ).not.toBeInTheDocument();
  });

  it('re-shows the conflict modal with fresh data if replacing hits a new conflict', async () => {
    const okRun: AllocationRun = {
      id: 'run-9b',
      project_id: 'proj-1',
      created_at: '2026-08-17T00:00:00Z',
      algorithm_version: 'v1',
      status: 'ok',
      lines: [],
      orphaned_materials: [],
      supplier_summaries: [
        {
          supplier_id: 'sup-a',
          goods_total: 120,
          delivery_fee: 0,
          free_shipping_achieved: true,
          below_min_order: false,
        },
      ],
    };
    runMock.mockResolvedValue(okRun);
    pricesListMock.mockResolvedValue([]);
    const firstConflict: OrderDraftConflict = {
      detail: 'draft_orders_exist',
      suppliers_with_existing_drafts: [
        {
          supplier_id: 'sup-a',
          supplier_name: 'ABC Supply',
          existing_draft_orders: [
            { order_id: 'ord-1', total_amount: 120, has_confirmed_prices: false },
          ],
        },
      ],
    };
    const raceConflict: OrderDraftConflict = {
      detail: 'draft_orders_exist',
      suppliers_with_existing_drafts: [
        {
          supplier_id: 'sup-a',
          supplier_name: 'ABC Supply',
          existing_draft_orders: [
            { order_id: 'ord-1', total_amount: 120, has_confirmed_prices: false },
            { order_id: 'ord-race', total_amount: 120, has_confirmed_prices: false },
          ],
        },
      ],
    };
    createOrdersMock.mockRejectedValueOnce(new ApiError(409, firstConflict));
    createOrdersMock.mockRejectedValueOnce(new ApiError(409, raceConflict));

    renderPage();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Подтвердить и создать ордера/ }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getAllByText('$120.00')).toHaveLength(1);

    await user.click(within(dialog).getByRole('button', { name: /Заменить черновики/ }));

    const refreshedDialog = await screen.findByRole('dialog');
    expect(within(refreshedDialog).getAllByText('$120.00')).toHaveLength(2);
  });

  it('closes the conflict modal without creating anything when cancelled', async () => {
    const okRun: AllocationRun = {
      id: 'run-10',
      project_id: 'proj-1',
      created_at: '2026-08-17T00:00:00Z',
      algorithm_version: 'v1',
      status: 'ok',
      lines: [],
      orphaned_materials: [],
      supplier_summaries: [
        {
          supplier_id: 'sup-a',
          goods_total: 120,
          delivery_fee: 0,
          free_shipping_achieved: true,
          below_min_order: false,
        },
      ],
    };
    runMock.mockResolvedValue(okRun);
    pricesListMock.mockResolvedValue([]);
    const conflict: OrderDraftConflict = {
      detail: 'draft_orders_exist',
      suppliers_with_existing_drafts: [
        {
          supplier_id: 'sup-a',
          supplier_name: 'ABC Supply',
          existing_draft_orders: [
            { order_id: 'ord-1', total_amount: 120, has_confirmed_prices: false },
          ],
        },
      ],
    };
    createOrdersMock.mockRejectedValueOnce(new ApiError(409, conflict));

    renderPage();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Подтвердить и создать ордера/ }));
    await screen.findByRole('dialog');
    await user.click(screen.getByRole('button', { name: /Отмена/ }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(createOrdersMock).toHaveBeenCalledTimes(1);
  });

  it('shows "изменено после отправки ордера" when overridden_at is after ordered_at', async () => {
    const okRun: AllocationRun = {
      id: 'run-5',
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
          overridden_at: '2026-08-18T12:00:00Z',
          original_supplier_id: 'sup-b',
          original_unit_price: 15,
          ordered_at: '2026-08-18T10:00:00Z',
        },
      ],
      orphaned_materials: [],
      supplier_summaries: [
        {
          supplier_id: 'sup-a',
          goods_total: 120,
          delivery_fee: 0,
          free_shipping_achieved: true,
          below_min_order: false,
        },
      ],
    };
    runMock.mockResolvedValue(okRun);
    pricesListMock.mockResolvedValue([
      { id: 'p1', material_id: 'mat-1', supplier_id: 'sup-a', price: 12, currency: 'USD', availability: 100, min_order_qty: null, valid_from: '2026-01-01', valid_to: null, source_import_id: null },
    ] satisfies Price[]);

    renderPage();

    expect(await screen.findByText(/изменено после отправки ордера/)).toBeInTheDocument();
  });

  it('does not show "изменено после отправки ордера" when the override happened before ordering', async () => {
    const okRun: AllocationRun = {
      id: 'run-6',
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
          overridden_at: '2026-08-18T08:00:00Z',
          original_supplier_id: 'sup-b',
          original_unit_price: 15,
          ordered_at: '2026-08-18T10:00:00Z',
        },
      ],
      orphaned_materials: [],
      supplier_summaries: [
        {
          supplier_id: 'sup-a',
          goods_total: 120,
          delivery_fee: 0,
          free_shipping_achieved: true,
          below_min_order: false,
        },
      ],
    };
    runMock.mockResolvedValue(okRun);
    pricesListMock.mockResolvedValue([
      { id: 'p1', material_id: 'mat-1', supplier_id: 'sup-a', price: 12, currency: 'USD', availability: 100, min_order_qty: null, valid_from: '2026-01-01', valid_to: null, source_import_id: null },
    ] satisfies Price[]);

    renderPage();

    expect(await screen.findByText(supplierA.name)).toBeInTheDocument();
    expect(screen.queryByText(/изменено после отправки ордера/)).not.toBeInTheDocument();
  });
});
