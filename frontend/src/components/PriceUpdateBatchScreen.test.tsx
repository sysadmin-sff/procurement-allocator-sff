import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { PriceUpdateBatchScreen } from './PriceUpdateBatchScreen';
import type { PriceDivergence, PriceUpdateResult } from '../api/types';

interface Row {
  order_item_id: string;
  divergence: PriceDivergence;
  materialName: string;
  supplierName: string;
}

const rows: Row[] = [
  {
    order_item_id: 'item-1',
    materialName: 'Сетка Fiberglass 18x14',
    supplierName: 'ABC Supply',
    divergence: {
      action: 'update',
      material_id: 'mat-1',
      supplier_id: 'sup-a',
      current_price: 12.5,
      confirmed_price: 12.47,
    },
  },
  {
    order_item_id: 'item-2',
    materialName: 'Профиль алюминиевый',
    supplierName: 'Florida Sales',
    divergence: {
      action: 'create',
      material_id: 'mat-2',
      supplier_id: 'sup-b',
      current_price: null,
      confirmed_price: 9.99,
    },
  },
];

describe('PriceUpdateBatchScreen', () => {
  it('lists only the divergent rows with material, supplier, current and new price', () => {
    render(<PriceUpdateBatchScreen rows={rows} results={null} onSubmit={vi.fn()} />);

    expect(screen.getByText('Сетка Fiberglass 18x14')).toBeInTheDocument();
    expect(screen.getByText('Профиль алюминиевый')).toBeInTheDocument();
    expect(screen.getByText('$12.50')).toBeInTheDocument();
    expect(screen.getByText(/нет активной цены/i)).toBeInTheDocument();
  });

  it('defaults every checkbox to unchecked', () => {
    render(<PriceUpdateBatchScreen rows={rows} results={null} onSubmit={vi.fn()} />);

    for (const checkbox of screen.getAllByRole('checkbox')) {
      expect(checkbox).not.toBeChecked();
    }
  });

  it('submits only the checked rows as apply:true selections, including unchecked ones as apply:false', async () => {
    const onSubmit = vi.fn();
    render(<PriceUpdateBatchScreen rows={rows} results={null} onSubmit={onSubmit} />);

    const user = userEvent.setup();
    const checkboxes = screen.getAllByRole('checkbox');
    await user.click(checkboxes[0]);
    await user.click(screen.getByRole('button', { name: /Обновить выбранные цены в базе/ }));

    expect(onSubmit).toHaveBeenCalledWith([
      { order_item_id: 'item-1', apply: true },
      { order_item_id: 'item-2', apply: false },
    ]);
  });

  it('shows a per-row result after submission, including an error for a stale row', () => {
    const results: PriceUpdateResult[] = [
      { order_item_id: 'item-1', applied: true, price_id: 'price-1', action: 'update', error: null },
      {
        order_item_id: 'item-2',
        applied: false,
        price_id: null,
        action: null,
        error: 'stale: confirmed_price changed or price already matches',
      },
    ];
    render(<PriceUpdateBatchScreen rows={rows} results={results} onSubmit={vi.fn()} />);

    expect(screen.getByText(/обновлено/i)).toBeInTheDocument();
    expect(screen.getByText(/stale: confirmed_price changed or price already matches/)).toBeInTheDocument();
  });
});
