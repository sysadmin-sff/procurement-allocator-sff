import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { OrderDeleteModal } from './OrderDeleteModal';

describe('OrderDeleteModal', () => {
  it('shows the confirmation text', () => {
    render(<OrderDeleteModal hasConfirmedPrices={false} onConfirm={vi.fn()} onCancel={vi.fn()} />);

    expect(screen.getByText(/Удалить ордер\? Это необратимо\./)).toBeInTheDocument();
  });

  it('shows the confirmed-prices warning when the order has confirmed or received prices', () => {
    render(<OrderDeleteModal hasConfirmedPrices onConfirm={vi.fn()} onCancel={vi.fn()} />);

    expect(
      screen.getByText(/В этом ордере есть подтверждённые цены — они будут потеряны безвозвратно\./),
    ).toBeInTheDocument();
  });

  it('does not show the warning when the order has no confirmed or received prices', () => {
    render(<OrderDeleteModal hasConfirmedPrices={false} onConfirm={vi.fn()} onCancel={vi.fn()} />);

    expect(screen.queryByText(/подтверждённые цены/)).not.toBeInTheDocument();
  });

  it('calls onConfirm when "Удалить" is clicked', async () => {
    const onConfirm = vi.fn();
    render(<OrderDeleteModal hasConfirmedPrices={false} onConfirm={onConfirm} onCancel={vi.fn()} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Удалить' }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('calls onCancel when "Отмена" is clicked and does not call onConfirm', async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<OrderDeleteModal hasConfirmedPrices={false} onConfirm={onConfirm} onCancel={onCancel} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Отмена' }));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
