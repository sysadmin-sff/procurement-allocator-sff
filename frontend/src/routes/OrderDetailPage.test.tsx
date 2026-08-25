import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OrderDetailPage } from './OrderDetailPage';
import { ApiError } from '../api/client';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import { suppliersApi } from '../api/suppliers';
import type { Material, Order, OrderItem, Supplier } from '../api/types';

vi.mock('../api/orders', () => ({
  ordersApi: {
    createForRun: vi.fn(),
    listForProject: vi.fn(),
    get: vi.fn(),
    patchItem: vi.fn(),
    findReplacement: vi.fn(),
    replaceAndOrder: vi.fn(),
  },
}));
vi.mock('../api/materials', () => ({
  materialsApi: { list: vi.fn(), search: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../api/suppliers', () => ({
  suppliersApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const getOrderMock = vi.mocked(ordersApi.get);
const patchItemMock = vi.mocked(ordersApi.patchItem);
const findReplacementMock = vi.mocked(ordersApi.findReplacement);
const replaceAndOrderMock = vi.mocked(ordersApi.replaceAndOrder);
const materialsListMock = vi.mocked(materialsApi.list);
const suppliersListMock = vi.mocked(suppliersApi.list);

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
    received_price: null,
    confirmed_price: null,
    confirmed_at: null,
    declined_at: null,
    decline_reason: null,
    price_delta: null,
    price_delta_pct: null,
    replaced_by_supplier_id: null,
    replaced_by_supplier_name: null,
    replacement_draft_order_id: null,
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
    patchItemMock.mockReset();
    findReplacementMock.mockReset();
    replaceAndOrderMock.mockReset();
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
    patchItemMock.mockResolvedValue(
      itemFixture({ confirmed_price: 27.5, confirmed_at: '2026-08-18T10:00:00Z', price_delta: 2.5, price_delta_pct: 10.0 }),
    );

    renderPage();

    const inputs = await screen.findAllByPlaceholderText('—');
    const confirmedInput = inputs[1]; // received price, confirmed price, in column order
    const user = userEvent.setup();
    await user.type(confirmedInput, '27.50');
    await user.tab();

    expect(patchItemMock).toHaveBeenCalledWith('order-1', 'item-1', { confirmed_price: 27.5 });
    expect(await screen.findByText(/\+\$2\.50 \(\+10\.0%\)/)).toBeInTheDocument();
  });

  it('saves received_price on blur without touching confirmed_price', async () => {
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
    patchItemMock.mockResolvedValue(itemFixture({ received_price: 23.75 }));

    renderPage();

    const inputs = await screen.findAllByPlaceholderText('—');
    const receivedInput = inputs[0];
    const user = userEvent.setup();
    await user.type(receivedInput, '23.75');
    await user.tab();

    expect(patchItemMock).toHaveBeenCalledWith('order-1', 'item-1', { received_price: 23.75 });
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

  it('renders received_price and shows decline reason for a declined row', async () => {
    const order: Order = {
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [
        itemFixture({
          received_price: 23.75,
          declined_at: '2026-08-18T10:00:00Z',
          decline_reason: 'нет в наличии',
        }),
      ],
    };
    getOrderMock.mockResolvedValue(order);

    renderPage();

    expect(await screen.findByDisplayValue('23.75')).toBeInTheDocument();
    expect(screen.getByText('Отклонено')).toBeInTheDocument();
    expect(screen.getByDisplayValue('нет в наличии')).toBeInTheDocument();
    expect(await screen.findByText(/1 позиция отклонено поставщиком/)).toBeInTheDocument();
  });

  it('marks a row as declined when the decline button is clicked', async () => {
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
    patchItemMock.mockResolvedValue(itemFixture({ declined_at: '2026-08-18T10:00:00Z' }));

    renderPage();

    const button = await screen.findByText('Отметить как недоступно');
    const user = userEvent.setup();
    await user.click(button);

    expect(patchItemMock).toHaveBeenCalledWith('order-1', 'item-1', { declined: true });
  });

  it('un-declines a row when the active decline button is clicked again', async () => {
    const order: Order = {
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [itemFixture({ declined_at: '2026-08-18T10:00:00Z' })],
    };
    getOrderMock.mockResolvedValue(order);
    patchItemMock.mockResolvedValue(itemFixture({ declined_at: null, decline_reason: null }));

    renderPage();

    const button = await screen.findByText('Отклонено');
    const user = userEvent.setup();
    await user.click(button);

    expect(patchItemMock).toHaveBeenCalledWith('order-1', 'item-1', { declined: false });
  });

  it('sorts declined rows to the bottom, keeping non-declined rows in their original order', async () => {
    const order: Order = {
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [
        itemFixture({ id: 'item-1', material_id: 'mat-1', declined_at: '2026-08-18T10:00:00Z' }),
        itemFixture({ id: 'item-2', material_id: 'mat-2' }),
        itemFixture({ id: 'item-3', material_id: 'mat-3', declined_at: '2026-08-18T11:00:00Z' }),
        itemFixture({ id: 'item-4', material_id: 'mat-4' }),
      ],
    };
    getOrderMock.mockResolvedValue(order);
    materialsListMock.mockResolvedValue([
      material,
      { ...material, id: 'mat-2', canonical_name: 'Material Two' },
      { ...material, id: 'mat-3', canonical_name: 'Material Three' },
      { ...material, id: 'mat-4', canonical_name: 'Material Four' },
    ]);

    renderPage();

    const rows = await screen.findAllByRole('row');
    // rows[0] is the header row.
    const materialCells = rows.slice(1).map((row) => row.querySelector('td')?.textContent);
    expect(materialCells).toEqual(['Material Two', 'Material Four', material.canonical_name, 'Material Three']);
  });

  it('moves a row to the bottom immediately after it is declined, without waiting for a refetch', async () => {
    const order: Order = {
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [
        itemFixture({ id: 'item-1', material_id: 'mat-1' }),
        itemFixture({ id: 'item-2', material_id: 'mat-2' }),
      ],
    };
    getOrderMock.mockResolvedValue(order);
    materialsListMock.mockResolvedValue([material, { ...material, id: 'mat-2', canonical_name: 'Material Two' }]);
    patchItemMock.mockResolvedValue(itemFixture({ id: 'item-1', declined_at: '2026-08-18T10:00:00Z' }));

    renderPage();

    const buttons = await screen.findAllByText('Отметить как недоступно');
    const user = userEvent.setup();
    await user.click(buttons[0]); // decline item-1 (originally first)

    await screen.findByText('Отклонено');
    const rows = await screen.findAllByRole('row');
    const materialCells = rows.slice(1).map((row) => row.querySelector('td')?.textContent);
    expect(materialCells).toEqual(['Material Two', material.canonical_name]);
  });

  it('renders copyable material lists with and without prices', async () => {
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

    const withPrices = await screen.findByText('Список материалов (с ценами)');
    const withoutPrices = screen.getByText('Список материалов (без цен)');
    expect(withPrices).toBeInTheDocument();
    expect(withoutPrices).toBeInTheDocument();

    const textareas = screen.getAllByRole('textbox') as HTMLTextAreaElement[];
    const withPricesText = textareas.find((t) => t.value.includes('Price:'));
    const withoutPricesText = textareas.find((t) => !t.value.includes('Price:'));

    expect(withPricesText?.value).toContain('Order for ABC Supply');
    expect(withPricesText?.value).toContain('Qty: 10 рулон');
    expect(withPricesText?.value).toContain('Grand total: $275.00');
    expect(withoutPricesText?.value).not.toContain('Total:');
    expect(withoutPricesText?.value).not.toContain('Grand total');
  });

  describe('find-replacement (ADR-0014)', () => {
    function declinedOrder(overrides: Partial<OrderItem> = {}): Order {
      return {
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture({ declined_at: '2026-08-18T10:00:00Z', decline_reason: 'нет в наличии', ...overrides })],
      };
    }

    it('does not show the find-replacement button on a non-declined row', async () => {
      getOrderMock.mockResolvedValue({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });

      renderPage();

      await screen.findByText(material.canonical_name);
      expect(screen.queryByText('Найти замену')).not.toBeInTheDocument();
    });

    it('shows candidates with an availability-risk warning when clicked', async () => {
      getOrderMock.mockResolvedValue(declinedOrder());
      findReplacementMock.mockResolvedValue({
        line_id: 'line-1',
        candidates: [
          { supplier_id: 'sup-b', supplier_name: 'Better Supply', price: 22, availability: 3, availability_risk: true },
          { supplier_id: 'sup-c', supplier_name: 'Other Supply', price: 24, availability: null, availability_risk: false },
        ],
      });

      renderPage();

      const trigger = await screen.findByText('Найти замену');
      const user = userEvent.setup();
      await user.click(trigger);

      expect(findReplacementMock).toHaveBeenCalledWith('order-1', 'item-1');
      expect(await screen.findByText('Better Supply')).toBeInTheDocument();
      expect(screen.getByText('Other Supply')).toBeInTheDocument();
      expect(screen.getByText(/у поставщика доступно 3 рулон, требуется 10/)).toBeInTheDocument();
    });

    it('shows a 404 inline under the button, not as a page-level error banner', async () => {
      getOrderMock.mockResolvedValue(declinedOrder());
      findReplacementMock.mockRejectedValue(
        new ApiError(404, { detail: 'материал Сетка Fiberglass 18x14 отсутствует в текущем плане проекта' }),
      );

      renderPage();

      const trigger = await screen.findByText('Найти замену');
      const user = userEvent.setup();
      await user.click(trigger);

      expect(
        await screen.findByText(/материал Сетка Fiberglass 18x14 отсутствует в текущем плане проекта/),
      ).toBeInTheDocument();
    });

    it('selecting a candidate calls replace-and-order and re-fetches the order, without navigating away', async () => {
      getOrderMock.mockResolvedValueOnce(declinedOrder());
      findReplacementMock.mockResolvedValue({
        line_id: 'line-1',
        candidates: [
          { supplier_id: 'sup-b', supplier_name: 'Better Supply', price: 22, availability: null, availability_risk: false },
        ],
      });
      replaceAndOrderMock.mockResolvedValue(
        itemFixture({
          declined_at: '2026-08-18T10:00:00Z',
          decline_reason: 'нет в наличии',
          replaced_by_supplier_id: 'sup-b',
          replaced_by_supplier_name: 'Better Supply',
          replacement_draft_order_id: null,
        }),
      );
      getOrderMock.mockResolvedValueOnce(
        declinedOrder({
          replaced_by_supplier_id: 'sup-b',
          replaced_by_supplier_name: 'Better Supply',
          replacement_draft_order_id: null,
        }),
      );

      renderPage();

      const trigger = await screen.findByText('Найти замену');
      const user = userEvent.setup();
      await user.click(trigger);

      const candidateButton = await screen.findByText('Better Supply');
      await user.click(candidateButton);

      expect(replaceAndOrderMock).toHaveBeenCalledWith('order-1', 'item-1', 'sup-b');
      expect(getOrderMock).toHaveBeenCalledTimes(2);

      expect(await screen.findByText(/→ Перенесено на Better Supply/)).toBeInTheDocument();
      expect(screen.getByText(/ордер ещё не создан/)).toBeInTheDocument();
      // Stayed on the Order page — no navigation to the project screen.
      expect(screen.queryByText('Project detail screen')).not.toBeInTheDocument();
    });

    it('shows a 409 conflict message inline under the panel, not as a page-level error banner', async () => {
      getOrderMock.mockResolvedValue(declinedOrder());
      findReplacementMock.mockResolvedValue({
        line_id: 'line-1',
        candidates: [
          { supplier_id: 'sup-b', supplier_name: 'Better Supply', price: 22, availability: null, availability_risk: false },
        ],
      });
      replaceAndOrderMock.mockRejectedValue(
        new ApiError(409, {
          detail:
            'У поставщика Better Supply уже есть 2 черновика ордеров по этому проекту — сначала определитесь, какой из них актуален, прежде чем переносить сюда позицию.',
        }),
      );

      renderPage();

      const trigger = await screen.findByText('Найти замену');
      const user = userEvent.setup();
      await user.click(trigger);

      const candidateButton = await screen.findByText('Better Supply');
      await user.click(candidateButton);

      expect(
        await screen.findByText(/уже есть 2 черновика ордеров по этому проекту/),
      ).toBeInTheDocument();
      // Stayed on the Order page — no navigation to the project screen.
      expect(screen.queryByText('Project detail screen')).not.toBeInTheDocument();
    });

    it('shows a link to the draft order when replacement_draft_order_id is set', async () => {
      getOrderMock.mockResolvedValue(
        declinedOrder({
          replaced_by_supplier_id: 'sup-b',
          replaced_by_supplier_name: 'Better Supply',
          replacement_draft_order_id: 'order-2',
        }),
      );

      renderPage();

      const link = await screen.findByText('черновик уже создан »');
      expect(link.closest('a')).toHaveAttribute('href', '/orders/order-2');
    });
  });
});
