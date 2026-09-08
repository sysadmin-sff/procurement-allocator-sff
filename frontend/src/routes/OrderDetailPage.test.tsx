import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OrderDetailPage } from './OrderDetailPage';
import { ApiError } from '../api/client';
import { materialsApi } from '../api/materials';
import { ordersApi } from '../api/orders';
import { projectsApi } from '../api/projects';
import { suppliersApi } from '../api/suppliers';
import type { Material, Order, OrderItem, ProjectWithItems, Supplier } from '../api/types';

vi.mock('../api/orders', () => ({
  ordersApi: {
    createForRun: vi.fn(),
    listForProject: vi.fn(),
    get: vi.fn(),
    patchItem: vi.fn(),
    findReplacement: vi.fn(),
    replaceAndOrder: vi.fn(),
    parseResponse: vi.fn(),
    confirmPriceUpdates: vi.fn(),
  },
}));
vi.mock('../api/materials', () => ({
  materialsApi: { list: vi.fn(), search: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../api/suppliers', () => ({
  suppliersApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../api/projects', () => ({
  projectsApi: {
    list: vi.fn(),
    create: vi.fn(),
    updateProject: vi.fn(),
    get: vi.fn(),
    addItem: vi.fn(),
    updateItem: vi.fn(),
    removeItem: vi.fn(),
    remove: vi.fn(),
    complete: vi.fn(),
  },
}));

const getOrderMock = vi.mocked(ordersApi.get);
const patchItemMock = vi.mocked(ordersApi.patchItem);
const findReplacementMock = vi.mocked(ordersApi.findReplacement);
const replaceAndOrderMock = vi.mocked(ordersApi.replaceAndOrder);
const parseResponseMock = vi.mocked(ordersApi.parseResponse);
const confirmPriceUpdatesMock = vi.mocked(ordersApi.confirmPriceUpdates);
const materialsListMock = vi.mocked(materialsApi.list);
const suppliersListMock = vi.mocked(suppliersApi.list);
const projectGetMock = vi.mocked(projectsApi.get);

function projectFixture(overrides: Partial<ProjectWithItems> = {}): ProjectWithItems {
  return {
    id: 'proj-1',
    title: 'Pool cage — Bayshore Rd',
    created_by: null,
    status: 'draft',
    created_at: '2026-08-17T00:00:00Z',
    color_choice: null,
    items: [],
    latest_allocation_run: null,
    ...overrides,
  };
}

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

/** Fills in the ADR-0026 derived fields with the "no declines" defaults
 * (declined_amount 0, expected_* mirroring the sent snapshot) so existing
 * fixtures don't need to compute them by hand; tests that care about
 * declines pass overrides explicitly. */
function orderFixture(base: {
  id: string;
  project_id: string;
  supplier_id: string;
  status: string;
  total_amount: number;
  delivery_fee: number;
  items: OrderItem[];
}, overrides: Partial<Pick<Order, 'tax_amount' | 'expected_goods_total' | 'expected_tax_amount' | 'expected_delivery_fee' | 'expected_total' | 'declined_amount' | 'fully_declined'>> = {}): Order {
  return {
    ...base,
    tax_amount: null,
    expected_goods_total: base.total_amount,
    expected_tax_amount: 0,
    expected_delivery_fee: base.delivery_fee,
    expected_total: base.total_amount + base.delivery_fee,
    declined_amount: 0,
    fully_declined: false,
    ...overrides,
  };
}

function itemFixture(overrides: Partial<OrderItem> = {}): OrderItem {
  return {
    id: 'item-1',
    order_id: 'order-1',
    material_id: 'mat-1',
    quantity: 10,
    quoted_price: 25,
    received_price: null,
    target_price: null,
    confirmed_price: null,
    confirmed_at: null,
    declined_at: null,
    decline_reason: null,
    price_delta: null,
    price_delta_pct: null,
    received_price_delta: null,
    received_price_delta_pct: null,
    replaced_by_supplier_id: null,
    replaced_by_supplier_name: null,
    replacement_draft_order_id: null,
    price_divergence: null,
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
    parseResponseMock.mockReset();
    confirmPriceUpdatesMock.mockReset();
    materialsListMock.mockReset();
    suppliersListMock.mockReset();
    projectGetMock.mockReset();
    materialsListMock.mockResolvedValue([material]);
    suppliersListMock.mockResolvedValue([supplier]);
    projectGetMock.mockResolvedValue(projectFixture());
  });

  it('renders quoted price and an empty confirmed-price cell when unconfirmed', async () => {
    const order: Order = orderFixture({
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [itemFixture()],
    });
    getOrderMock.mockResolvedValue(order);

    renderPage();

    expect(await screen.findByText(supplier.name)).toBeInTheDocument();
    expect(screen.getByText(material.canonical_name)).toBeInTheDocument();
    expect(screen.getByText('$25.00')).toBeInTheDocument();
    expect(screen.queryByText(/расхождением цены/)).not.toBeInTheDocument();
  });

  it('saves confirmed_price on blur and shows the resulting delta', async () => {
    const order: Order = orderFixture({
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [itemFixture()],
    });
    getOrderMock.mockResolvedValue(order);
    patchItemMock.mockResolvedValue(
      itemFixture({ confirmed_price: 27.5, confirmed_at: '2026-08-18T10:00:00Z', price_delta: 2.5, price_delta_pct: 10.0 }),
    );

    renderPage();

    const inputs = await screen.findAllByPlaceholderText('—');
    const confirmedInput = inputs[2]; // received, target, confirmed, in column order
    const user = userEvent.setup();
    await user.type(confirmedInput, '27.50');
    await user.tab();

    expect(patchItemMock).toHaveBeenCalledWith('order-1', 'item-1', { confirmed_price: 27.5 });
    expect(await screen.findByText(/\+\$2\.50 \(\+10\.0%\)/)).toBeInTheDocument();
  });

  it('saves received_price on blur without touching confirmed_price', async () => {
    const order: Order = orderFixture({
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [itemFixture()],
    });
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
    const order: Order = orderFixture({
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
    });
    getOrderMock.mockResolvedValue(order);

    renderPage();

    expect(await screen.findByText(/1 позиция с расхождением цены больше 10%/)).toBeInTheDocument();
    expect(screen.getByText(/\+\$4\.00 \(\+16\.0%\)/)).toBeInTheDocument();
  });

  it('does not flag a small discrepancy under the 10% threshold', async () => {
    const order: Order = orderFixture({
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
    });
    getOrderMock.mockResolvedValue(order);

    renderPage();

    await screen.findByText(material.canonical_name);
    expect(screen.queryByText(/расхождением цены/)).not.toBeInTheDocument();
  });

  it('renders received_price and shows decline reason for a declined row', async () => {
    const order: Order = orderFixture({
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
    });
    getOrderMock.mockResolvedValue(order);

    renderPage();

    expect(await screen.findByDisplayValue('23.75')).toBeInTheDocument();
    expect(screen.getByText('Отклонено')).toBeInTheDocument();
    expect(screen.getByDisplayValue('нет в наличии')).toBeInTheDocument();
    expect(await screen.findByText(/1 позиция отклонено поставщиком/)).toBeInTheDocument();
  });

  it('marks a row as declined when the decline button is clicked', async () => {
    const order: Order = orderFixture({
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [itemFixture()],
    });
    getOrderMock.mockResolvedValue(order);
    patchItemMock.mockResolvedValue(itemFixture({ declined_at: '2026-08-18T10:00:00Z' }));

    renderPage();

    const button = await screen.findByText('Отметить как недоступно');
    const user = userEvent.setup();
    await user.click(button);

    expect(patchItemMock).toHaveBeenCalledWith('order-1', 'item-1', { declined: true });
  });

  it('un-declines a row when the active decline button is clicked again', async () => {
    const order: Order = orderFixture({
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [itemFixture({ declined_at: '2026-08-18T10:00:00Z' })],
    });
    getOrderMock.mockResolvedValue(order);
    patchItemMock.mockResolvedValue(itemFixture({ declined_at: null, decline_reason: null }));

    renderPage();

    const button = await screen.findByText('Отклонено');
    const user = userEvent.setup();
    await user.click(button);

    expect(patchItemMock).toHaveBeenCalledWith('order-1', 'item-1', { declined: false });
  });

  it('sorts declined rows to the bottom, keeping non-declined rows in their original order', async () => {
    const order: Order = orderFixture({
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
    });
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
    const order: Order = orderFixture({
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
    });
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
    const order: Order = orderFixture({
      id: 'order-1',
      project_id: 'proj-1',
      supplier_id: 'sup-a',
      status: 'draft',
      total_amount: 250,
      delivery_fee: 25,
      items: [itemFixture()],
    });
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

  describe('footer totals: sent (DB snapshot) vs expected (confirmed prices)', () => {
    it('always shows the "Ожидается" block, even with nothing confirmed or declined', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);

      renderPage();

      await screen.findByText(material.canonical_name);
      expect(screen.getByText('Ожидается:')).toBeInTheDocument();
      // No confirmed_price anywhere -> falls back to quoted_price per item,
      // same goods total as the sent snapshot. tax_amount is null (fixture
      // default, ADR-0029 §4 "not tracked"), so "Отправлено" shows "—" for
      // tax while "Ожидается" computes its own 7% locally (250 * 0.07 = 17.50).
      expect(
        screen.getByText(/Товары \$250\.00 \+ Налог \(7%\) — \+ Доставка \$25\.00 = \$275\.00/),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Товары \$250\.00 \+ Налог \(7%\) \$17\.50 \+ Доставка \$25\.00 = \$292\.50/),
      ).toBeInTheDocument();
    });

    it('uses confirmed_price where set and quoted_price as a fallback where not', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 500,
        delivery_fee: 50,
        items: [
          itemFixture({ id: 'item-1', quoted_price: 100, quantity: 1, confirmed_price: 90 }),
          itemFixture({ id: 'item-2', material_id: 'mat-1', quoted_price: 400, quantity: 1 }),
        ],
      });
      getOrderMock.mockResolvedValue(order);

      renderPage();

      expect(await screen.findByText('Отправлено:')).toBeInTheDocument();
      // tax_amount is null on this fixture (ADR-0029 §4 default) -> "—".
      expect(
        screen.getByText(/Товары \$500\.00 \+ Налог \(7%\) — \+ Доставка \$50\.00 = \$550\.00/),
      ).toBeInTheDocument();
      expect(screen.getByText('Ожидается:')).toBeInTheDocument();
      // item-1: confirmed_price 90, item-2: no confirmed_price -> falls back
      // to quoted_price 400. 90 + 400 = 490, tax = 490 * 0.07 = 34.30,
      // + delivery 50 = 574.30.
      expect(
        screen.getByText(/Товары \$490\.00 \+ Налог \(7%\) \$34\.30 \+ Доставка \$50\.00 = \$574\.30/),
      ).toBeInTheDocument();
    });

    it('excludes declined items from the expected total, regardless of their confirmed_price', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 500,
        delivery_fee: 50,
        items: [
          itemFixture({
            id: 'item-1',
            quoted_price: 120,
            quantity: 1,
            confirmed_price: 999,
            declined_at: '2026-08-18T10:00:00Z',
          }),
          itemFixture({ id: 'item-2', material_id: 'mat-1', quoted_price: 380, quantity: 1, confirmed_price: 380 }),
        ],
      });
      getOrderMock.mockResolvedValue(order);

      renderPage();

      // tax on the expected (confirmed_price-based, non-declined-only) goods
      // total: 380 * 0.07 = 26.60.
      expect(
        await screen.findByText(/Товары \$380\.00 \+ Налог \(7%\) \$26\.60 \+ Доставка \$50\.00 = \$456\.60/),
      ).toBeInTheDocument();
    });
  });

  describe('find-replacement (ADR-0014)', () => {
    function declinedOrder(overrides: Partial<OrderItem> = {}): Order {
      return orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture({ declined_at: '2026-08-18T10:00:00Z', decline_reason: 'нет в наличии', ...overrides })],
      });
    }

    it('does not show the find-replacement button on a non-declined row', async () => {
      getOrderMock.mockResolvedValue(orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      }));

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

  describe('target_price column (ADR-0027)', () => {
    it('renders an empty target-price cell and saves it on blur', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);
      patchItemMock.mockResolvedValue(itemFixture({ target_price: 21.5 }));

      renderPage();

      // "Целевая" / "цена" render on separate lines via <br/>, so match the
      // header by its normalized textContent instead of an exact text node.
      expect(
        await screen.findByRole('columnheader', {
          name: (_, el) => el.textContent?.replace(/\s+/g, '') === 'Целеваяцена',
        }),
      ).toBeInTheDocument();
      const inputs = await screen.findAllByPlaceholderText('—');
      const targetInput = inputs[1]; // received, target, confirmed, in column order
      const user = userEvent.setup();
      await user.type(targetInput, '21.50');
      await user.tab();

      expect(patchItemMock).toHaveBeenCalledWith('order-1', 'item-1', { target_price: 21.5 });
    });

    it('places the target-price column between received and confirmed price', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);

      renderPage();

      // Two-word headers wrap onto a second line via <br/>, so textContent
      // concatenates without a space ("Полученнаяцена") — compare with
      // whitespace stripped instead of an exact string match.
      const headers = (await screen.findAllByRole('columnheader')).map((h) =>
        h.textContent?.replace(/\s+/g, ''),
      );
      const receivedIdx = headers.indexOf('Полученнаяцена');
      const targetIdx = headers.indexOf('Целеваяцена');
      const confirmedIdx = headers.indexOf('Подтверждённаяцена');
      expect(receivedIdx).toBeGreaterThanOrEqual(0);
      expect(targetIdx).toBe(receivedIdx + 1);
      expect(confirmedIdx).toBe(targetIdx + 1);
    });
  });

  describe('single-item price divergence popup (ADR-0030 п.4.2)', () => {
    it('does not show a popup when the PATCH response has no price_divergence', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);
      patchItemMock.mockResolvedValue(itemFixture({ confirmed_price: 27.5 }));

      renderPage();

      const inputs = await screen.findAllByPlaceholderText('—');
      const confirmedInput = inputs[2];
      const user = userEvent.setup();
      await user.type(confirmedInput, '27.50');
      await user.tab();

      await waitFor(() => expect(patchItemMock).toHaveBeenCalledWith('order-1', 'item-1', { confirmed_price: 27.5 }));
      expect(screen.queryByText(/Обновить цену в базе/)).not.toBeInTheDocument();
    });

    it('shows the popup with current/new price and action text when the PATCH response carries price_divergence', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);
      patchItemMock.mockResolvedValue(
        itemFixture({
          confirmed_price: 27.5,
          price_divergence: {
            action: 'update',
            material_id: 'mat-1',
            supplier_id: 'sup-a',
            current_price: 25,
            confirmed_price: 27.5,
          },
        }),
      );

      renderPage();

      const inputs = await screen.findAllByPlaceholderText('—');
      const confirmedInput = inputs[2];
      const user = userEvent.setup();
      await user.type(confirmedInput, '27.50');
      await user.tab();

      const modalTitle = await screen.findByText('Обновить цену в справочнике?');
      const modal = modalTitle.closest('[role="dialog"]') as HTMLElement;
      expect(within(modal).getByText(material.canonical_name)).toBeInTheDocument();
      expect(within(modal).getByText(supplier.name)).toBeInTheDocument();
      expect(within(modal).getByText('$25.00')).toBeInTheDocument();
      expect(within(modal).getByText('$27.50')).toBeInTheDocument();
    });

    it('shows "create" action text and no current price when action is create', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);
      patchItemMock.mockResolvedValue(
        itemFixture({
          confirmed_price: 9.99,
          price_divergence: {
            action: 'create',
            material_id: 'mat-1',
            supplier_id: 'sup-a',
            current_price: null,
            confirmed_price: 9.99,
          },
        }),
      );

      renderPage();

      const inputs = await screen.findAllByPlaceholderText('—');
      const confirmedInput = inputs[2];
      const user = userEvent.setup();
      await user.type(confirmedInput, '9.99');
      await user.tab();

      expect(await screen.findByText('Добавить цену в справочник?')).toBeInTheDocument();
      expect(screen.getByText(/нет активной цены/i)).toBeInTheDocument();
    });

    it('dismissing the popup does not roll back the already-saved confirmed_price', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);
      patchItemMock.mockResolvedValue(
        itemFixture({
          confirmed_price: 27.5,
          price_divergence: {
            action: 'update',
            material_id: 'mat-1',
            supplier_id: 'sup-a',
            current_price: 25,
            confirmed_price: 27.5,
          },
        }),
      );

      renderPage();

      const inputs = await screen.findAllByPlaceholderText('—');
      const confirmedInput = inputs[2];
      const user = userEvent.setup();
      await user.type(confirmedInput, '27.50');
      await user.tab();

      await screen.findByText('Обновить цену в справочнике?');
      // confirmed_price PATCH already resolved and applied to state before
      // the popup rendered — this assertion is what proves it (ADR-0030 п.7).
      expect(patchItemMock).toHaveBeenCalledWith('order-1', 'item-1', { confirmed_price: 27.5 });

      await user.click(screen.getByRole('button', { name: /Не обновлять/ }));

      expect(screen.queryByText('Обновить цену в справочнике?')).not.toBeInTheDocument();
      expect(confirmPriceUpdatesMock).not.toHaveBeenCalled();
      // The saved value is already reflected in state (proven by the
      // patchItemMock assertion above) — dismissing the popup issues no
      // further PATCH that could roll it back.
      expect(patchItemMock).toHaveBeenCalledTimes(1);
    });

    it('confirming the popup calls confirm-price-updates with a single-row selection', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);
      patchItemMock.mockResolvedValue(
        itemFixture({
          confirmed_price: 27.5,
          price_divergence: {
            action: 'update',
            material_id: 'mat-1',
            supplier_id: 'sup-a',
            current_price: 25,
            confirmed_price: 27.5,
          },
        }),
      );
      confirmPriceUpdatesMock.mockResolvedValue({
        results: [{ order_item_id: 'item-1', applied: true, price_id: 'price-1', action: 'update', error: null }],
      });

      renderPage();

      const inputs = await screen.findAllByPlaceholderText('—');
      const confirmedInput = inputs[2];
      const user = userEvent.setup();
      await user.type(confirmedInput, '27.50');
      await user.tab();

      await screen.findByText('Обновить цену в справочнике?');
      await user.click(screen.getByRole('button', { name: /Обновить цену в базе/ }));

      expect(confirmPriceUpdatesMock).toHaveBeenCalledWith('order-1', [{ order_item_id: 'item-1', apply: true }]);
    });
  });

  describe('second parse-response round (ADR-0027 §2)', () => {
    it('renders both parse-response blocks at once', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);

      renderPage();

      expect(await screen.findByText('Распознавание ответа поставщика')).toBeInTheDocument();
      expect(screen.getByText('Распознавание финального ответа (после торга)')).toBeInTheDocument();
    });

    it('applying matches from the first block PATCHes received_price', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);
      parseResponseMock.mockResolvedValue({
        matched: [
          { order_item_id: 'item-1', raw_description: 'Сетка', price: 23.75, quantity: 10, confidence: 'high', reasoning: '' },
        ],
        missing: [],
        extra: [],
      });
      patchItemMock.mockResolvedValue(itemFixture({ received_price: 23.75 }));

      renderPage();

      const firstBlockTitle = await screen.findByText('Распознавание ответа поставщика');
      const firstSection = firstBlockTitle.parentElement as HTMLElement;
      const fileInput = firstSection.querySelector('input[type="file"]') as HTMLInputElement;
      const file = new File(['x'], 'response.pdf', { type: 'application/pdf' });
      const user = userEvent.setup();
      await user.upload(fileInput, file);
      await user.click(within(firstSection).getByText('Распознать цены из документа'));

      const applyButton = await within(firstSection).findByText('Применить все совпадения');
      await user.click(applyButton);

      expect(patchItemMock).toHaveBeenCalledWith('order-1', 'item-1', { received_price: 23.75 });
    });

    it('applying matches from the second block PATCHes confirmed_price, not received_price', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);
      parseResponseMock.mockResolvedValue({
        matched: [
          { order_item_id: 'item-1', raw_description: 'Сетка', price: 22.0, quantity: 10, confidence: 'high', reasoning: '' },
        ],
        missing: [],
        extra: [],
      });
      patchItemMock.mockResolvedValue(itemFixture({ confirmed_price: 22.0 }));

      renderPage();

      const secondBlockTitle = await screen.findByText('Распознавание финального ответа (после торга)');
      const secondSection = secondBlockTitle.parentElement as HTMLElement;
      const fileInput = secondSection.querySelector('input[type="file"]') as HTMLInputElement;
      const file = new File(['x'], 'final.pdf', { type: 'application/pdf' });
      const user = userEvent.setup();
      await user.upload(fileInput, file);
      await user.click(within(secondSection).getByText('Распознать цены из документа'));

      const applyButton = await within(secondSection).findByText('Применить все совпадения');
      await user.click(applyButton);

      expect(patchItemMock).toHaveBeenCalledWith('order-1', 'item-1', { confirmed_price: 22.0 });
      expect(patchItemMock).not.toHaveBeenCalledWith('order-1', 'item-1', { received_price: 22.0 });
    });

    it('does not show the batch screen when the applied batch has no price divergences', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture({ id: 'item-1' })],
      });
      getOrderMock.mockResolvedValue(order);
      parseResponseMock.mockResolvedValue({
        matched: [
          { order_item_id: 'item-1', raw_description: 'Сетка', price: 22.0, quantity: 10, confidence: 'high', reasoning: '' },
        ],
        missing: [],
        extra: [],
      });
      patchItemMock.mockResolvedValue(itemFixture({ confirmed_price: 22.0, price_divergence: null }));

      renderPage();

      const secondBlockTitle = await screen.findByText('Распознавание финального ответа (после торга)');
      const secondSection = secondBlockTitle.parentElement as HTMLElement;
      const fileInput = secondSection.querySelector('input[type="file"]') as HTMLInputElement;
      const file = new File(['x'], 'final.pdf', { type: 'application/pdf' });
      const user = userEvent.setup();
      await user.upload(fileInput, file);
      await user.click(within(secondSection).getByText('Распознать цены из документа'));
      const applyButton = await within(secondSection).findByText('Применить все совпадения');
      await user.click(applyButton);

      await screen.findByText(/Применено 1 из 1/);
      expect(screen.queryByText(/Расхождения со справочником цен/)).not.toBeInTheDocument();
    });

    it('shows the batch screen with only divergent rows, unchecked by default, after batch application', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 500,
        delivery_fee: 50,
        items: [
          itemFixture({ id: 'item-1', material_id: 'mat-1' }),
          itemFixture({ id: 'item-2', material_id: 'mat-2' }),
        ],
      });
      getOrderMock.mockResolvedValue(order);
      materialsListMock.mockResolvedValue([
        material,
        { id: 'mat-2', internal_sku: 'PRF-AL-1', canonical_name: 'Профиль алюминиевый', category: null, unit: 'шт', attributes: {} },
      ]);
      parseResponseMock.mockResolvedValue({
        matched: [
          { order_item_id: 'item-1', raw_description: 'Сетка', price: 22.0, quantity: 10, confidence: 'high', reasoning: '' },
          { order_item_id: 'item-2', raw_description: 'Профиль', price: 9.99, quantity: 5, confidence: 'high', reasoning: '' },
        ],
        missing: [],
        extra: [],
      });
      patchItemMock.mockImplementation((_orderId, itemId) => {
        if (itemId === 'item-1') {
          return Promise.resolve(
            itemFixture({
              id: 'item-1',
              material_id: 'mat-1',
              confirmed_price: 22.0,
              price_divergence: {
                action: 'update',
                material_id: 'mat-1',
                supplier_id: 'sup-a',
                current_price: 25,
                confirmed_price: 22.0,
              },
            }),
          );
        }
        return Promise.resolve(
          itemFixture({ id: 'item-2', material_id: 'mat-2', confirmed_price: 9.99, price_divergence: null }),
        );
      });

      renderPage();

      const secondBlockTitle = await screen.findByText('Распознавание финального ответа (после торга)');
      const secondSection = secondBlockTitle.parentElement as HTMLElement;
      const fileInput = secondSection.querySelector('input[type="file"]') as HTMLInputElement;
      const file = new File(['x'], 'final.pdf', { type: 'application/pdf' });
      const user = userEvent.setup();
      await user.upload(fileInput, file);
      await user.click(within(secondSection).getByText('Распознать цены из документа'));
      const applyButton = await within(secondSection).findByText('Применить все совпадения');
      await user.click(applyButton);

      const batchTitle = await screen.findByText(/Расхождения со справочником цен \(1\)/);
      const batchSection = batchTitle.parentElement as HTMLElement;
      expect(within(batchSection).getByText('Сетка Fiberglass 18x14')).toBeInTheDocument();
      expect(within(batchSection).queryByText('Профиль алюминиевый')).not.toBeInTheDocument();
      const checkbox = within(batchSection).getByRole('checkbox');
      expect(checkbox).not.toBeChecked();
    });

    it('shows a per-row error when confirm-price-updates rejects a stale row', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture({ id: 'item-1', material_id: 'mat-1' })],
      });
      getOrderMock.mockResolvedValue(order);
      parseResponseMock.mockResolvedValue({
        matched: [
          { order_item_id: 'item-1', raw_description: 'Сетка', price: 22.0, quantity: 10, confidence: 'high', reasoning: '' },
        ],
        missing: [],
        extra: [],
      });
      patchItemMock.mockResolvedValue(
        itemFixture({
          id: 'item-1',
          material_id: 'mat-1',
          confirmed_price: 22.0,
          price_divergence: {
            action: 'update',
            material_id: 'mat-1',
            supplier_id: 'sup-a',
            current_price: 25,
            confirmed_price: 22.0,
          },
        }),
      );
      confirmPriceUpdatesMock.mockResolvedValue({
        results: [
          {
            order_item_id: 'item-1',
            applied: false,
            price_id: null,
            action: null,
            error: 'stale: confirmed_price changed or price already matches',
          },
        ],
      });

      renderPage();

      const secondBlockTitle = await screen.findByText('Распознавание финального ответа (после торга)');
      const secondSection = secondBlockTitle.parentElement as HTMLElement;
      const fileInput = secondSection.querySelector('input[type="file"]') as HTMLInputElement;
      const file = new File(['x'], 'final.pdf', { type: 'application/pdf' });
      const user = userEvent.setup();
      await user.upload(fileInput, file);
      await user.click(within(secondSection).getByText('Распознать цены из документа'));
      const applyButton = await within(secondSection).findByText('Применить все совпадения');
      await user.click(applyButton);

      const batchTitle = await screen.findByText(/Расхождения со справочником цен \(1\)/);
      const batchSection = batchTitle.parentElement as HTMLElement;
      await user.click(within(batchSection).getByRole('checkbox'));
      await user.click(within(batchSection).getByRole('button', { name: /Обновить выбранные цены в базе/ }));

      expect(await screen.findByText(/stale: confirmed_price changed or price already matches/)).toBeInTheDocument();
    });
  });

  describe('buildOrderText excludes declined items (ADR-0027 §5)', () => {
    it('omits declined items and renumbers sequentially, using expected_* totals', async () => {
      const order: Order = orderFixture(
        {
          id: 'order-1',
          project_id: 'proj-1',
          supplier_id: 'sup-a',
          status: 'draft',
          total_amount: 500,
          delivery_fee: 50,
          items: [
            itemFixture({ id: 'item-1', material_id: 'mat-1', declined_at: '2026-08-18T10:00:00Z' }),
            itemFixture({ id: 'item-2', material_id: 'mat-2' }),
            itemFixture({ id: 'item-3', material_id: 'mat-3' }),
          ],
        },
        {
          expected_goods_total: 380,
          expected_delivery_fee: 50,
          expected_total: 430,
          declined_amount: 120,
          fully_declined: false,
        },
      );
      getOrderMock.mockResolvedValue(order);
      materialsListMock.mockResolvedValue([
        material,
        { ...material, id: 'mat-2', canonical_name: 'Material Two' },
        { ...material, id: 'mat-3', canonical_name: 'Material Three' },
      ]);

      renderPage();

      await screen.findByText('Список материалов (с ценами)');
      const textareas = screen.getAllByRole('textbox') as HTMLTextAreaElement[];
      const withPricesText = textareas.find((t) => t.value.includes('Price:'))!.value;

      expect(withPricesText).not.toContain(material.canonical_name);
      expect(withPricesText).toContain('1. Material Two');
      expect(withPricesText).toContain('2. Material Three');
      expect(withPricesText).not.toMatch(/3\./);
      expect(withPricesText).toContain('Goods total: $380.00');
      expect(withPricesText).toContain('Delivery: $50.00');
      expect(withPricesText).toContain('Grand total: $430.00');
    });

    it('matches prior behavior exactly when nothing is declined', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);

      renderPage();

      await screen.findByText('Список материалов (с ценами)');
      const textareas = screen.getAllByRole('textbox') as HTMLTextAreaElement[];
      const withPricesText = textareas.find((t) => t.value.includes('Price:'))!.value;

      expect(withPricesText).toContain('Order for ABC Supply');
      expect(withPricesText).toContain('1. ' + material.canonical_name);
      expect(withPricesText).toContain('Grand total: $275.00');
    });
  });

  describe('copyable list with target prices (ADR-0027)', () => {
    function getBlockTextarea(title: string): HTMLTextAreaElement {
      const heading = screen.getByText(title);
      // heading is .copyBlockTitle, its parent is .copyBlockHeader, and the
      // textarea is a sibling of .copyBlockHeader inside .copyBlock.
      const block = heading.parentElement?.parentElement as HTMLElement;
      return within(block).getByRole('textbox') as HTMLTextAreaElement;
    }

    it('includes only items with a target_price set, using target_price for the per-line and total figures', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 500,
        delivery_fee: 50,
        items: [
          itemFixture({ id: 'item-1', material_id: 'mat-1', target_price: 20, quantity: 1 }),
          itemFixture({ id: 'item-2', material_id: 'mat-2', target_price: null }),
          itemFixture({ id: 'item-3', material_id: 'mat-3', target_price: 30, quantity: 2 }),
        ],
      });
      getOrderMock.mockResolvedValue(order);
      materialsListMock.mockResolvedValue([
        material,
        { ...material, id: 'mat-2', canonical_name: 'Material Two' },
        { ...material, id: 'mat-3', canonical_name: 'Material Three' },
      ]);

      renderPage();

      await screen.findByText('Список материалов (с целевыми ценами)');
      const text = getBlockTextarea('Список материалов (с целевыми ценами)').value;

      expect(text).toContain('1. ' + material.canonical_name);
      expect(text).toContain('Price: $20.00/unit');
      expect(text).toContain('Total: $20.00');
      expect(text).not.toContain('Material Two');
      expect(text).toContain('2. Material Three');
      expect(text).toContain('Price: $30.00/unit');
      expect(text).toContain('Total: $60.00');
      expect(text).toContain('Goods total: $80.00');
    });

    it('excludes declined items even if they have a target_price', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [
          itemFixture({ target_price: 20, declined_at: '2026-08-18T10:00:00Z' }),
        ],
      });
      getOrderMock.mockResolvedValue(order);

      renderPage();

      await screen.findByText('Список материалов (с целевыми ценами)');
      const text = getBlockTextarea('Список материалов (с целевыми ценами)').value;

      expect(text).not.toContain(material.canonical_name);
      expect(text).toContain('Goods total: $0.00');
    });

    it('shows an empty-list message when no item has a target_price', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture({ target_price: null })],
      });
      getOrderMock.mockResolvedValue(order);

      renderPage();

      await screen.findByText('Список материалов (с целевыми ценами)');
      const text = getBlockTextarea('Список материалов (с целевыми ценами)').value;

      expect(text).toContain('Goods total: $0.00');
      expect(text).not.toContain(material.canonical_name);
    });
  });

  describe('color resolution in copyable lists (ADR-0031 §5)', () => {
    const twoColorMaterial: Material = {
      id: 'mat-color',
      internal_sku: 'GTR-EC-5',
      canonical_name: 'Super Gutter End Cap 5" (White/Bronze)',
      category: 'Gutter',
      unit: 'шт',
      attributes: {},
      color_options: ['White', 'Bronze'],
      color_fragment: '(White/Bronze)',
    };

    it('resolves a two-color material to the project color_choice in buildOrderText, showing one color not both', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 100,
        delivery_fee: 25,
        items: [itemFixture({ material_id: 'mat-color', quantity: 2, quoted_price: 50 })],
      });
      getOrderMock.mockResolvedValue(order);
      materialsListMock.mockResolvedValue([twoColorMaterial]);
      projectGetMock.mockResolvedValue(projectFixture({ color_choice: 'White' }));

      renderPage();

      await screen.findByText('Список материалов (с ценами)');
      const textareas = screen.getAllByRole('textbox') as HTMLTextAreaElement[];
      const withPricesText = textareas.find((t) => t.value.includes('Price:'))!.value;

      expect(withPricesText).toContain('Super Gutter End Cap 5" (White)');
      expect(withPricesText).not.toContain('(White/Bronze)');
      expect(withPricesText).not.toContain('(Bronze)');
    });

    it('resolves the same material in buildTargetPriceOrderText using the same logic', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 100,
        delivery_fee: 25,
        items: [itemFixture({ material_id: 'mat-color', quantity: 2, target_price: 45 })],
      });
      getOrderMock.mockResolvedValue(order);
      materialsListMock.mockResolvedValue([twoColorMaterial]);
      projectGetMock.mockResolvedValue(projectFixture({ color_choice: 'Bronze' }));

      renderPage();

      await screen.findByText('Список материалов (с целевыми ценами)');
      const heading = screen.getByText('Список материалов (с целевыми ценами)');
      const block = heading.parentElement?.parentElement as HTMLElement;
      const text = (within(block).getByRole('textbox') as HTMLTextAreaElement).value;

      expect(text).toContain('Super Gutter End Cap 5" (Bronze)');
      expect(text).not.toContain('(White/Bronze)');
      expect(text).not.toContain('(White)');
    });

    it('leaves a material without color_options unchanged (regression)', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 250,
        delivery_fee: 25,
        items: [itemFixture()],
      });
      getOrderMock.mockResolvedValue(order);
      projectGetMock.mockResolvedValue(projectFixture({ color_choice: 'White' }));

      renderPage();

      await screen.findByText('Список материалов (с ценами)');
      const textareas = screen.getAllByRole('textbox') as HTMLTextAreaElement[];
      const withPricesText = textareas.find((t) => t.value.includes('Price:'))!.value;

      expect(withPricesText).toContain(material.canonical_name);
    });

    it('does not crash and falls back to canonical_name as-is when color_choice is not set', async () => {
      const order: Order = orderFixture({
        id: 'order-1',
        project_id: 'proj-1',
        supplier_id: 'sup-a',
        status: 'draft',
        total_amount: 100,
        delivery_fee: 25,
        items: [itemFixture({ material_id: 'mat-color', quantity: 2, quoted_price: 50 })],
      });
      getOrderMock.mockResolvedValue(order);
      materialsListMock.mockResolvedValue([twoColorMaterial]);
      projectGetMock.mockResolvedValue(projectFixture({ color_choice: null }));

      renderPage();

      await screen.findByText('Список материалов (с ценами)');
      const textareas = screen.getAllByRole('textbox') as HTMLTextAreaElement[];
      const withPricesText = textareas.find((t) => t.value.includes('Price:'))!.value;

      expect(withPricesText).toContain('Super Gutter End Cap 5" (White/Bronze)');
    });
  });
});
