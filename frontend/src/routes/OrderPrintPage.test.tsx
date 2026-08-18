import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OrderPrintPage } from './OrderPrintPage';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import { suppliersApi } from '../api/suppliers';
import type { Material, Order, Supplier } from '../api/types';

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
const materialsListMock = vi.mocked(materialsApi.list);
const suppliersListMock = vi.mocked(suppliersApi.list);

const supplier: Supplier = {
  id: 'sup-a',
  name: 'ABC Supply',
  contacts: '123 Main St, Tampa FL',
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

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/orders/order-1/print']}>
      <Routes>
        <Route path="/orders/:orderId/print" element={<OrderPrintPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('OrderPrintPage', () => {
  beforeEach(() => {
    getOrderMock.mockReset();
    materialsListMock.mockReset();
    suppliersListMock.mockReset();
    materialsListMock.mockResolvedValue([material]);
    suppliersListMock.mockResolvedValue([supplier]);
  });

  it('shows quoted_price only — no confirmed_price or delta columns', async () => {
    const order: Order = {
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [
        {
          id: 'item-1',
          order_id: 'order-1',
          material_id: 'mat-1',
          quantity: 10,
          quoted_price: 25,
          confirmed_price: 30,
          confirmed_at: '2026-08-18T10:00:00Z',
          price_delta: 5,
          price_delta_pct: 20,
        },
      ],
    };
    getOrderMock.mockResolvedValue(order);

    renderPage();

    expect(await screen.findByText(supplier.name)).toBeInTheDocument();
    expect(screen.getByText(supplier.contacts as string)).toBeInTheDocument();
    expect(screen.getByText(material.canonical_name)).toBeInTheDocument();
    expect(screen.getAllByText('$25.00').length).toBeGreaterThan(0);
    expect(screen.queryByText('$30.00')).not.toBeInTheDocument();
    expect(screen.queryByText(/20\.0%/)).not.toBeInTheDocument();
  });

  it('shows goods, delivery and grand totals', async () => {
    const order: Order = {
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [],
    };
    getOrderMock.mockResolvedValue(order);

    renderPage();

    expect(await screen.findByText('$250.00')).toBeInTheDocument();
    expect(screen.getByText('$25.00')).toBeInTheDocument();
    expect(screen.getByText('$275.00')).toBeInTheDocument();
  });
});
