import { render, screen } from '@testing-library/react';
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
        onReplace={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('JM Fasteners')).toBeInTheDocument();
    expect(screen.getByText('Florida Sales & Marketing')).toBeInTheDocument();
    // supplier A has two existing drafts at the same amount — both rendered, not collapsed.
    expect(screen.getAllByText('$346.30')).toHaveLength(2);
    expect(screen.getByText('$596.35')).toBeInTheDocument();
  });

  it('calls onReplace with no extra confirmation when no supplier has confirmed prices', async () => {
    const onReplace = vi.fn();
    render(
      <OrderDraftConflictModal
        conflict={conflictWithoutConfirmedPrices}
        onReplace={onReplace}
        onCancel={vi.fn()}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Заменить черновики/ }));

    expect(onReplace).toHaveBeenCalledTimes(1);
  });

  it('does not offer an "add additional" action — the backend has no way to fulfill it without replace_drafts', () => {
    render(
      <OrderDraftConflictModal
        conflict={conflictWithoutConfirmedPrices}
        onReplace={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole('button', { name: /Создать дополнительно/ }),
    ).not.toBeInTheDocument();
  });

  it('shows a distinct warning for a supplier whose draft has confirmed prices', () => {
    render(
      <OrderDraftConflictModal
        conflict={conflictWithConfirmedPrices}
        onReplace={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/в этом черновике уже есть подтверждённые поставщиком цены/i),
    ).toBeInTheDocument();
  });

  it('disables "Заменить черновики" until the confirmed-price acknowledgement checkbox is checked', async () => {
    const onReplace = vi.fn();
    render(
      <OrderDraftConflictModal
        conflict={conflictWithConfirmedPrices}
        onReplace={onReplace}
        onCancel={vi.fn()}
      />,
    );

    const replaceButton = screen.getByRole('button', { name: /Заменить черновики/ });
    expect(replaceButton).toBeDisabled();

    const user = userEvent.setup();
    await user.click(
      screen.getByRole('checkbox', { name: /понимаю, что подтверждённые цены будут потеряны/i }),
    );

    expect(replaceButton).toBeEnabled();
    await user.click(replaceButton);
    expect(onReplace).toHaveBeenCalledTimes(1);
  });

  it('shows an irreversibility hint for the replace action', () => {
    render(
      <OrderDraftConflictModal
        conflict={conflictWithoutConfirmedPrices}
        onReplace={vi.fn()}
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
        onReplace={vi.fn()}
        onCancel={onCancel}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Отмена/ }));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
