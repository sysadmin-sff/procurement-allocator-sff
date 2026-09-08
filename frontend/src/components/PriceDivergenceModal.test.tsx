import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { PriceDivergenceModal } from './PriceDivergenceModal';
import type { PriceDivergence } from '../api/types';

const updateDivergence: PriceDivergence = {
  action: 'update',
  material_id: 'mat-1',
  supplier_id: 'sup-a',
  current_price: 12.5,
  confirmed_price: 12.47,
};

const createDivergence: PriceDivergence = {
  action: 'create',
  material_id: 'mat-1',
  supplier_id: 'sup-a',
  current_price: null,
  confirmed_price: 9.99,
};

describe('PriceDivergenceModal', () => {
  it('shows material, supplier, current and new price for an update divergence', () => {
    render(
      <PriceDivergenceModal
        divergence={updateDivergence}
        materialName="Сетка Fiberglass 18x14"
        supplierName="ABC Supply"
        onConfirm={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.getByText('Сетка Fiberglass 18x14')).toBeInTheDocument();
    expect(screen.getByText('ABC Supply')).toBeInTheDocument();
    expect(screen.getByText('$12.50')).toBeInTheDocument();
    expect(screen.getByText('$12.47')).toBeInTheDocument();
  });

  it('shows "нет активной цены" instead of a current price for a create divergence', () => {
    render(
      <PriceDivergenceModal
        divergence={createDivergence}
        materialName="Сетка Fiberglass 18x14"
        supplierName="ABC Supply"
        onConfirm={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.getByText(/нет активной цены/i)).toBeInTheDocument();
  });

  it('calls onConfirm when "Обновить цену в базе" is clicked', async () => {
    const onConfirm = vi.fn();
    render(
      <PriceDivergenceModal
        divergence={updateDivergence}
        materialName="Сетка Fiberglass 18x14"
        supplierName="ABC Supply"
        onConfirm={onConfirm}
        onDismiss={vi.fn()}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Обновить цену в базе/ }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('calls onDismiss when "Не обновлять" is clicked', async () => {
    const onDismiss = vi.fn();
    render(
      <PriceDivergenceModal
        divergence={updateDivergence}
        materialName="Сетка Fiberglass 18x14"
        supplierName="ABC Supply"
        onConfirm={vi.fn()}
        onDismiss={onDismiss}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Не обновлять/ }));

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
