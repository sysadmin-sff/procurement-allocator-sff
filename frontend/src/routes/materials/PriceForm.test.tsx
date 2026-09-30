import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { PriceForm } from './PriceForm';
import type { Supplier } from '../../api/types';

const supplier: Supplier = {
  id: 'sup-a',
  name: 'JM Fasteners',
  short_name: null,
  contacts: null,
  currency: 'USD',
  delivery_policy: { flat_fee: 0, free_shipping_threshold: 0, per_order_min_amount: 0, lead_time_days: 1 },
  website: null,
  region: null,
  catalog_link: null,
  status: null,
  payment_terms: null,
  portal_url: null,
  comments: null,
  is_active_for_allocation: true,
};

describe('PriceForm', () => {
  it('accepts a 3-decimal price, matching the Numeric(12,3) backend column', async () => {
    const onSubmitCreate = vi.fn().mockResolvedValue(undefined);
    render(
      <PriceForm materialId="mat-1" suppliers={[supplier]} onCancel={() => {}} onSubmitCreate={onSubmitCreate} />,
    );

    const priceInput = screen.getByLabelText('Цена');
    expect(priceInput).toHaveAttribute('step', '0.001');

    const user = userEvent.setup();
    await user.clear(priceInput);
    await user.type(priceInput, '0.625');
    await user.click(screen.getByText('Добавить цену'));

    expect(onSubmitCreate).toHaveBeenCalledWith(
      expect.objectContaining({ price: 0.625 }),
    );
  });
});
