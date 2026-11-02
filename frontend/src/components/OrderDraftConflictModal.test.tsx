import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { OrderDraftConflictModal } from './OrderDraftConflictModal';
import type { OrderDraftConflict } from '../api/types';

const conflictWithoutConfirmedPrices: OrderDraftConflict = {
  detail: 'draft_orders_exist',
  suppliers_with_existing_drafts: [
    {
      supplier_id: 'sup-a',
      supplier_name: 'JM Fasteners',
      existing_draft_orders: [
        { order_id: 'ord-1', total_amount: 346.3, has_confirmed_prices: false },
        { order_id: 'ord-2', total_amount: 346.3, has_confirmed_prices: false },
      ],
    },
    {
      supplier_id: 'sup-b',
      supplier_name: 'Florida Sales & Marketing',
      existing_draft_orders: [
        { order_id: 'ord-3', total_amount: 596.35, has_confirmed_prices: false },
      ],
    },
  ],
};

const conflictWithConfirmedPrices: OrderDraftConflict = {
  detail: 'draft_orders_exist',
  suppliers_with_existing_drafts: [
    {
      supplier_id: 'sup-a',
      supplier_name: 'JM Fasteners',
      existing_draft_orders: [
        { order_id: 'ord-1', total_amount: 346.3, has_confirmed_prices: false },
      ],
    },
    {
      supplier_id: 'sup-c',
      supplier_name: 'American Metals Supply',
      existing_draft_orders: [
        { order_id: 'ord-4', total_amount: 725.03, has_confirmed_prices: true },
      ],
    },
  ],
};

describe('OrderDraftConflictModal', () => {
  it('lists every conflicting supplier with each of its existing draft orders and totals', () => {
    render(
      <OrderDraftConflictModal
        conflict={conflictWithoutConfirmedPrices}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('JM Fasteners')).toBeInTheDocument();
    expect(screen.getByText('Florida Sales & Marketing')).toBeInTheDocument();
    // supplier A has two existing drafts at the same amount — both rendered, not collapsed.
    expect(screen.getAllByText('$346.30')).toHaveLength(2);
    expect(screen.getByText('$596.35')).toBeInTheDocument();
  });

  it('shows a distinct warning for a supplier whose draft has confirmed prices', () => {
    render(
      <OrderDraftConflictModal
        conflict={conflictWithConfirmedPrices}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/в этом черновике уже есть подтверждённые поставщиком цены/i),
    ).toBeInTheDocument();
  });

  it('shows an irreversibility hint for the replace action', () => {
    render(
      <OrderDraftConflictModal
        conflict={conflictWithoutConfirmedPrices}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText(/необратимо/i)).toBeInTheDocument();
  });

  it('calls onCancel when dismissed', async () => {
    const onCancel = vi.fn();
    render(
      <OrderDraftConflictModal
        conflict={conflictWithoutConfirmedPrices}
        onSubmit={vi.fn()}
        onCancel={onCancel}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Отмена/ }));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  describe('per-supplier actions (ADR-0048)', () => {
    function choose(supplierName: string, action: RegExp) {
      return within(screen.getByRole('radiogroup', { name: supplierName })).getByRole('radio', { name: action });
    }

    it('offers Заменить / Создать дополнительно / Не создавать for each supplier, none preselected', () => {
      render(<OrderDraftConflictModal conflict={conflictWithoutConfirmedPrices} onSubmit={vi.fn()} onCancel={vi.fn()} />);

      for (const name of ['JM Fasteners', 'Florida Sales & Marketing']) {
        const group = screen.getByRole('radiogroup', { name });
        const radios = within(group).getAllByRole('radio');
        expect(radios.map((r) => r.closest('label')?.textContent?.trim())).toEqual([
          'Заменить',
          'Создать дополнительно',
          'Не создавать',
        ]);
        for (const radio of radios) expect(radio).not.toBeChecked();
      }
      expect(screen.getByRole('button', { name: 'Создать ордера' })).toBeDisabled();
    });

    it('submits a supplier_id -> action map once every supplier has a choice', async () => {
      const onSubmit = vi.fn();
      render(<OrderDraftConflictModal conflict={conflictWithoutConfirmedPrices} onSubmit={onSubmit} onCancel={vi.fn()} />);
      const user = userEvent.setup();

      await user.click(choose('JM Fasteners', /Не создавать/));
      expect(screen.getByRole('button', { name: 'Создать ордера' })).toBeDisabled();
      await user.click(choose('Florida Sales & Marketing', /Заменить/));
      await user.click(screen.getByRole('button', { name: 'Создать ордера' }));

      expect(onSubmit).toHaveBeenCalledWith({ 'sup-a': 'skip', 'sup-b': 'replace' });
    });

    it('does not ask for the confirmed-price acknowledgement when that supplier is not being replaced', async () => {
      const onSubmit = vi.fn();
      render(<OrderDraftConflictModal conflict={conflictWithConfirmedPrices} onSubmit={onSubmit} onCancel={vi.fn()} />);
      const user = userEvent.setup();

      await user.click(choose('JM Fasteners', /Заменить/));
      await user.click(choose('American Metals Supply', /Создать дополнительно/));

      expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Создать ордера' }));
      expect(onSubmit).toHaveBeenCalledWith({ 'sup-a': 'replace', 'sup-c': 'add' });
    });

    it('requires the confirmed-price acknowledgement when a supplier with confirmed prices is set to Заменить', async () => {
      const onSubmit = vi.fn();
      render(<OrderDraftConflictModal conflict={conflictWithConfirmedPrices} onSubmit={onSubmit} onCancel={vi.fn()} />);
      const user = userEvent.setup();

      await user.click(choose('JM Fasteners', /Не создавать/));
      await user.click(choose('American Metals Supply', /Заменить/));

      const submit = screen.getByRole('button', { name: 'Создать ордера' });
      expect(submit).toBeDisabled();
      await user.click(screen.getByRole('checkbox', { name: /понимаю, что подтверждённые цены будут потеряны/i }));
      expect(submit).toBeEnabled();
      await user.click(submit);
      expect(onSubmit).toHaveBeenCalledWith({ 'sup-a': 'skip', 'sup-c': 'replace' });
    });
  });
});
