import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectDetailPage } from './ProjectDetailPage';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import { projectsApi } from '../api/projects';
import { suppliersApi } from '../api/suppliers';
import type { Material, Order, ProjectWithItems, Supplier } from '../api/types';

vi.mock('../api/projects', () => ({
  projectsApi: {
    list: vi.fn(),
    create: vi.fn(),
    get: vi.fn(),
    addItem: vi.fn(),
    updateItem: vi.fn(),
    removeItem: vi.fn(),
  },
}));
vi.mock('../api/materials', () => ({
  materialsApi: { list: vi.fn(), search: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../api/suppliers', () => ({
  suppliersApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../api/orders', () => ({
  ordersApi: {
    createForRun: vi.fn(),
    listForProject: vi.fn(),
    get: vi.fn(),
    setConfirmedPrice: vi.fn(),
  },
}));

const getMock = vi.mocked(projectsApi.get);
const addItemMock = vi.mocked(projectsApi.addItem);
const updateItemMock = vi.mocked(projectsApi.updateItem);
const removeItemMock = vi.mocked(projectsApi.removeItem);
const materialsListMock = vi.mocked(materialsApi.list);
const materialsSearchMock = vi.mocked(materialsApi.search);
const suppliersListMock = vi.mocked(suppliersApi.list);
const ordersListForProjectMock = vi.mocked(ordersApi.listForProject);

const material: Material = {
  id: 'mat-1',
  internal_sku: 'MSH-FG-1814',
  canonical_name: 'Сетка Fiberglass 18x14',
  category: 'Сетка',
  unit: 'рулон',
  attributes: {},
};

const material2: Material = {
  id: 'mat-2',
  internal_sku: 'FSTN-SMS-8',
  canonical_name: '#8 Self-Tapping Screw 1"',
  category: 'fastener',
  unit: 'box',
  attributes: {},
};

/** Fills in the ADR-0026 derived fields with the "no declines" defaults
 * (declined_amount 0, expected_* mirroring the sent snapshot); tests here
 * don't exercise declines except via the explicit fully_declined override. */
function orderFixture(base: {
  id: string;
  project_id: string;
  supplier_id: string;
  status: string;
  total_amount: number;
  delivery_fee: number;
  items: Order['items'];
}, overrides: Partial<Pick<Order, 'expected_goods_total' | 'expected_delivery_fee' | 'expected_total' | 'declined_amount' | 'fully_declined'>> = {}): Order {
  return {
    ...base,
    expected_goods_total: base.total_amount,
    expected_delivery_fee: base.delivery_fee,
    expected_total: base.total_amount + base.delivery_fee,
    declined_amount: 0,
    fully_declined: false,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/projects/proj-1']}>
      <Routes>
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="/projects/:projectId/allocation" element={<div>Allocation screen</div>} />
        <Route path="/orders/:orderId" element={<div>Order detail screen</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ProjectDetailPage', () => {
  beforeEach(() => {
    getMock.mockReset();
    addItemMock.mockReset();
    updateItemMock.mockReset();
    removeItemMock.mockReset();
    materialsListMock.mockReset();
    materialsSearchMock.mockReset();
    suppliersListMock.mockReset();
    ordersListForProjectMock.mockReset();
    materialsListMock.mockResolvedValue([material, material2]);
    suppliersListMock.mockResolvedValue([]);
    ordersListForProjectMock.mockResolvedValue([]);
  });

  it('shows "Рассчитать закупку" and no run summary when there is no prior run', async () => {
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [{ id: 'item-1', project_id: 'proj-1', material_id: 'mat-1', quantity: 10 }],
      latest_allocation_run: null,
    };
    getMock.mockResolvedValue(project);

    renderPage();

    expect(await screen.findByText(material.canonical_name)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Рассчитать закупку/ })).toBeInTheDocument();
    expect(screen.queryByText(/Последний расчёт/)).not.toBeInTheDocument();
  });

  it('shows "Пересчитать закупку" and the run summary when a prior run exists', async () => {
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [{ id: 'item-1', project_id: 'proj-1', material_id: 'mat-1', quantity: 10 }],
      latest_allocation_run: { id: 'run-1', created_at: '2026-08-17T12:00:00Z', status: 'ok' },
    };
    getMock.mockResolvedValue(project);

    renderPage();

    expect(await screen.findByRole('button', { name: /Пересчитать закупку/ })).toBeInTheDocument();
    expect(screen.getByText(/Последний расчёт/)).toBeInTheDocument();
  });

  it('navigates to the allocation screen when the calculate button is clicked', async () => {
    const user = userEvent.setup();
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [],
      latest_allocation_run: null,
    };
    getMock.mockResolvedValue(project);

    renderPage();

    await user.click(await screen.findByRole('button', { name: /Рассчитать закупку/ }));

    expect(await screen.findByText('Allocation screen')).toBeInTheDocument();
  });

  it('saves a quantity change on blur', async () => {
    const user = userEvent.setup();
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [{ id: 'item-1', project_id: 'proj-1', material_id: 'mat-1', quantity: 10 }],
      latest_allocation_run: null,
    };
    getMock.mockResolvedValue(project);
    updateItemMock.mockResolvedValue({ id: 'item-1', project_id: 'proj-1', material_id: 'mat-1', quantity: 25 });

    renderPage();

    const qtyInput = await screen.findByDisplayValue('10');
    await user.clear(qtyInput);
    await user.type(qtyInput, '25');
    await user.tab();

    expect(updateItemMock).toHaveBeenCalledWith('proj-1', 'item-1', 25);
  });

  it('removes an item after confirming delete', async () => {
    const user = userEvent.setup();
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [{ id: 'item-1', project_id: 'proj-1', material_id: 'mat-1', quantity: 10 }],
      latest_allocation_run: null,
    };
    getMock.mockResolvedValue(project);
    removeItemMock.mockResolvedValue(undefined);

    renderPage();

    await screen.findByText(material.canonical_name);
    await user.click(screen.getByRole('button', { name: 'Удалить' }));
    await user.click(screen.getByRole('button', { name: 'Да' }));

    expect(removeItemMock).toHaveBeenCalledWith('proj-1', 'item-1');
    await screen.findByPlaceholderText('Название или артикул…');
    expect(screen.queryByText(material.canonical_name)).not.toBeInTheDocument();
  });

  it('adds a new item by selecting a material and entering a quantity', async () => {
    const user = userEvent.setup();
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [],
      latest_allocation_run: null,
    };
    getMock.mockResolvedValue(project);
    materialsSearchMock.mockResolvedValue([material2]);
    addItemMock.mockResolvedValue({
      id: 'item-new',
      project_id: 'proj-1',
      material_id: 'mat-2',
      quantity: 7,
    });

    renderPage();

    const materialInput = await screen.findByPlaceholderText('Название или артикул…');
    await user.type(materialInput, 'screw');
    const option = await screen.findByText(material2.canonical_name);
    await user.click(option);

    const qtyInput = screen.getByPlaceholderText('0');
    await user.type(qtyInput, '7');

    await user.click(screen.getByRole('button', { name: /Добавить/ }));

    expect(addItemMock).toHaveBeenCalledWith('proj-1', { material_id: 'mat-2', quantity: 7 });
    expect(await screen.findByText(material2.canonical_name)).toBeInTheDocument();
  });

  it('shows an orders section with a link to each order once orders exist', async () => {
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [],
      latest_allocation_run: { id: 'run-1', created_at: '2026-08-17T12:00:00Z', status: 'ok' },
    };
    const supplier: Supplier = {
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
    const order: Order = orderFixture({
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 150,
      delivery_fee: 25,
      items: [],
    });
    getMock.mockResolvedValue(project);
    suppliersListMock.mockResolvedValue([supplier]);
    ordersListForProjectMock.mockResolvedValue([order]);

    renderPage();

    expect(await screen.findByText('Ордера')).toBeInTheDocument();
    expect(screen.getByText(supplier.name)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Открыть »' })).toHaveAttribute('href', '/orders/order-1');
  });

  it('shows a "Полностью отклонён" badge for an order with fully_declined true', async () => {
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [],
      latest_allocation_run: { id: 'run-1', created_at: '2026-08-17T12:00:00Z', status: 'ok' },
    };
    const supplier: Supplier = {
      id: 'sup-a',
      name: 'Lancing',
      short_name: null,
      contacts: null,
      currency: 'USD',
      delivery_policy: { flat_fee: 95, free_shipping_threshold: 500, per_order_min_amount: 0, lead_time_days: 3 },
      website: null,
      region: null,
      catalog_link: null,
      status: null,
      payment_terms: null,
      portal_url: null,
      comments: null,
    };
    const fullyDeclinedOrder: Order = orderFixture(
      {
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 148.26,
        delivery_fee: 95,
        items: [],
      },
      { expected_goods_total: 0, expected_delivery_fee: 0, expected_total: 0, declined_amount: 148.26, fully_declined: true },
    );
    getMock.mockResolvedValue(project);
    suppliersListMock.mockResolvedValue([supplier]);
    ordersListForProjectMock.mockResolvedValue([fullyDeclinedOrder]);

    renderPage();

    expect(await screen.findByText('Lancing')).toBeInTheDocument();
    expect(screen.getByText('Полностью отклонён')).toBeInTheDocument();
  });

  it('does not show the "Полностью отклонён" badge for a partially declined order', async () => {
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [],
      latest_allocation_run: { id: 'run-1', created_at: '2026-08-17T12:00:00Z', status: 'ok' },
    };
    const supplier: Supplier = {
      id: 'sup-a',
      name: 'ABC Supply',
      short_name: null,
      contacts: null,
      currency: 'USD',
      delivery_policy: { flat_fee: 50, free_shipping_threshold: 500, per_order_min_amount: 0, lead_time_days: 3 },
      website: null,
      region: null,
      catalog_link: null,
      status: null,
      payment_terms: null,
      portal_url: null,
      comments: null,
    };
    const partiallyDeclinedOrder: Order = orderFixture(
      {
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 500,
        delivery_fee: 50,
        items: [],
      },
      { expected_goods_total: 380, expected_delivery_fee: 50, expected_total: 430, declined_amount: 120, fully_declined: false },
    );
    getMock.mockResolvedValue(project);
    suppliersListMock.mockResolvedValue([supplier]);
    ordersListForProjectMock.mockResolvedValue([partiallyDeclinedOrder]);

    renderPage();

    expect(await screen.findByText(supplier.name)).toBeInTheDocument();
    expect(screen.queryByText('Полностью отклонён')).not.toBeInTheDocument();
  });

  it('navigates to the order screen when clicking anywhere on the order row, not just "Открыть »"', async () => {
    const supplier: Supplier = {
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
    const order: Order = orderFixture({
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 150,
      delivery_fee: 25,
      items: [],
    });
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [],
      latest_allocation_run: { id: 'run-1', created_at: '2026-08-17T12:00:00Z', status: 'ok' },
    };
    getMock.mockResolvedValue(project);
    suppliersListMock.mockResolvedValue([supplier]);
    ordersListForProjectMock.mockResolvedValue([order]);

    renderPage();

    const supplierCell = await screen.findByText(supplier.name);
    const user = userEvent.setup();
    await user.click(supplierCell);

    expect(await screen.findByText('Order detail screen')).toBeInTheDocument();
  });

  it('hides the orders section when there are no orders yet', async () => {
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [],
      latest_allocation_run: null,
    };
    getMock.mockResolvedValue(project);

    renderPage();

    await screen.findByRole('button', { name: /Рассчитать закупку/ });
    expect(screen.queryByText('Ордера')).not.toBeInTheDocument();
  });

  it('groups the spec table by material category with contiguous numbering', async () => {
    const materialNoCategory: Material = {
      id: 'mat-3',
      internal_sku: 'MISC-001',
      canonical_name: 'Разное крепление',
      category: null,
      unit: 'шт',
      attributes: {},
    };
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [
        { id: 'item-1', project_id: 'proj-1', material_id: 'mat-2', quantity: 5 }, // fastener
        { id: 'item-2', project_id: 'proj-1', material_id: 'mat-1', quantity: 2 }, // Сетка
        { id: 'item-3', project_id: 'proj-1', material_id: 'mat-3', quantity: 1 }, // no category
        { id: 'item-4', project_id: 'proj-1', material_id: 'mat-2', quantity: 3 }, // fastener again
      ],
      latest_allocation_run: null,
    };
    getMock.mockResolvedValue(project);
    materialsListMock.mockResolvedValue([material, material2, materialNoCategory]);

    renderPage();

    await screen.findAllByText(material2.canonical_name);

    const categoryHeaders = screen.getAllByText(/^(fastener|Сетка|Без категории)$/);
    // First-appearance order: fastener (item-1) before Сетка (item-2) before
    // "Без категории" (item-3) — even though item-4 (fastener again) comes
    // later in the input, it must not create a second "fastener" header.
    expect(categoryHeaders.map((el) => el.textContent)).toEqual(['fastener', 'Сетка', 'Без категории']);

    const rowNumberCells = document.querySelectorAll('td');
    const numbers = [...rowNumberCells]
      .map((td) => td.textContent)
      .filter((text): text is string => /^[1-4]$/.test(text ?? ''));
    // Contiguous 1..4 across all groups, in the order rows are rendered
    // (both fastener rows — item-1 and item-4 — end up adjacent under the
    // same header despite not being adjacent in the input).
    expect(numbers).toEqual(['1', '2', '3', '4']);
  });

  it('puts items with no category in a single trailing group, not scattered by input order', async () => {
    const materialNoCategory: Material = {
      id: 'mat-3',
      internal_sku: 'MISC-001',
      canonical_name: 'Разное крепление',
      category: null,
      unit: 'шт',
      attributes: {},
    };
    const project: ProjectWithItems = {
      id: 'proj-1',
      title: 'Pool cage — Bayshore Rd',
      created_by: null,
      status: 'draft',
      created_at: '2026-08-17T00:00:00Z',
      items: [
        { id: 'item-1', project_id: 'proj-1', material_id: 'mat-3', quantity: 1 }, // no category, first in input
        { id: 'item-2', project_id: 'proj-1', material_id: 'mat-1', quantity: 2 }, // Сетка
      ],
      latest_allocation_run: null,
    };
    getMock.mockResolvedValue(project);
    materialsListMock.mockResolvedValue([material, material2, materialNoCategory]);

    renderPage();

    await screen.findByText(material.canonical_name);

    const categoryHeaders = screen.getAllByText(/^(Сетка|Без категории)$/);
    expect(categoryHeaders.map((el) => el.textContent)).toEqual(['Сетка', 'Без категории']);
  });
});
