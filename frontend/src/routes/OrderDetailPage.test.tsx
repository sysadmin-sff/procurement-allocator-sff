import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OrderDetailPage } from './OrderDetailPage';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import { suppliersApi } from '../api/suppliers';
import type { Material, Order, OrderItem, Supplier } from '../api/types';

vi.mock('../api/orders', () => ({
  ordersApi: {
    createForRun: vi.fn(),
    listForProject: vi.fn(),
    get: vi.fn(),
    setConfirmedPrice: vi.fn(),
  },
}));
vi.mock('../api/materials', () => ({
  materialsApi: { list: vi.fn(), search: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../api/suppliers', () => ({
  suppliersApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const getOrderMock = vi.mocked(ordersApi.get);
const setConfirmedPriceMock = vi.mocked(ordersApi.setConfirmedPrice);
const materialsListMock = vi.mocked(materialsApi.list);
const suppliersListMock = vi.mocked(suppliersApi.list);

const supplier: Supplier = {
  id: 'sup-a',
  name: 'ABC Supply',
  contacts: null,
  currency: 'USD',
  delivery_policy: { flat_fee: 25, free_shipping_threshold: 500, per_order_min_amount: 0, lead_time_days: 3 },
};

const material: Material = {
  id: 'mat-1',
  internal_sku: 'MSH-FG-1814',
  canonical_name: 'Сетка Fiberglass 18x14',
  category: 'Сетка',
  unit: 'рулон',
  attributes: {},
};

function itemFixture(overrides: Partial<OrderItem> = {}): OrderItem {
  return {
    id: 'item-1',
    order_id: 'order-1',
    material_id: 'mat-1',
    quantity: 10,
    quoted_price: 25,
    confirmed_price: null,
    confirmed_at: null,
    price_delta: null,
    price_delta_pct: null,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/orders/order-1']}>
      <Routes>
        <Route path="/orders/:orderId" element={<OrderDetailPage />} />
        <Route path="/projects/:projectId" element={<div>Project detail screen</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('OrderDetailPage', () => {
  beforeEach(() => {
    getOrderMock.mockReset();
    setConfirmedPriceMock.mockReset();
    materialsListMock.mockReset();
    suppliersListMock.mockReset();
    materialsListMock.mockResolvedValue([material]);
    suppliersListMock.mockResolvedValue([supplier]);
  });

  it('renders quoted price and an empty confirmed-price cell when unconfirmed', async () => {
    const order: Order = {
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [itemFixture()],
    };
    getOrderMock.mockResolvedValue(order);

    renderPage();

    expect(await screen.findByText(supplier.name)).toBeInTheDocument();
    expect(screen.getByText(material.canonical_name)).toBeInTheDocument();
    expect(screen.getByText('$25.00')).toBeInTheDocument();
    expect(screen.queryByText(/расхождением цены/)).not.toBeInTheDocument();
  });

  it('saves confirmed_price on blur and shows the resulting delta', async () => {
    const order: Order = {
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [itemFixture()],
    };
    getOrderMock.mockResolvedValue(order);
    setConfirmedPriceMock.mockResolvedValue(
      itemFixture({ confirmed_price: 27.5, confirmed_at: '2026-08-18T10:00:00Z', price_delta: 2.5, price_delta_pct: 10.0 }),
    );

    renderPage();

    const input = await screen.findByPlaceholderText('—');
    const user = userEvent.setup();
    await user.type(input, '27.50');
    await user.tab();

    expect(setConfirmedPriceMock).toHaveBeenCalledWith('order-1', 'item-1', 27.5);
    expect(await screen.findByText(/\+\$2\.50 \(\+10\.0%\)/)).toBeInTheDocument();
  });

  it('highlights the row and shows the summary banner when |price_delta_pct| > 10', async () => {
    const order: Order = {
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [
        itemFixture({
          id: 'item-1',
          confirmed_price: 29,
          confirmed_at: '2026-08-18T10:00:00Z',
          price_delta: 4,
          price_delta_pct: 16,
        }),
      ],
    };
    getOrderMock.mockResolvedValue(order);

    renderPage();

    expect(await screen.findByText(/1 позиция с расхождением цены больше 10%/)).toBeInTheDocument();
    expect(screen.getByText(/\+\$4\.00 \(\+16\.0%\)/)).toBeInTheDocument();
  });

  it('does not flag a small discrepancy under the 10% threshold', async () => {
    const order: Order = {
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [
        itemFixture({
          confirmed_price: 25.5,
          confirmed_at: '2026-08-18T10:00:00Z',
          price_delta: 0.5,
          price_delta_pct: 2.0,
        }),
      ],
    };
    getOrderMock.mockResolvedValue(order);

    renderPage();

    await screen.findByText(material.canonical_name);
    expect(screen.queryByText(/расхождением цены/)).not.toBeInTheDocument();
  });

  it('links to the print view', async () => {
    const order: Order = {
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [itemFixture()],
    };
    getOrderMock.mockResolvedValue(order);

    renderPage();

    expect(await screen.findByRole('link', { name: /Печатная версия/ })).toHaveAttribute(
      'href',
      '/orders/order-1/print',
    );
  });
});
