import { describe, expect, it } from 'vitest';
import { summarizeDeliveryPolicy } from './deliveryPolicySummary';

describe('summarizeDeliveryPolicy', () => {
  it('distinguishes an unset threshold (null) from an explicit $0 threshold', () => {
    const unset = summarizeDeliveryPolicy({
      flat_fee: 15,
      free_shipping_threshold: null,
      per_order_min_amount: 0,
      lead_time_days: 0,
    });
    const zero = summarizeDeliveryPolicy({
      flat_fee: 15,
      free_shipping_threshold: 0,
      per_order_min_amount: 0,
      lead_time_days: 0,
    });

    expect(unset).toContain('порог не задан');
    expect(zero).toContain('порог $0.00');
    expect(unset).not.toEqual(zero);
  });

  it('formats a positive threshold as a dollar amount', () => {
    const summary = summarizeDeliveryPolicy({
      flat_fee: 15,
      free_shipping_threshold: 250,
      per_order_min_amount: 0,
      lead_time_days: 0,
    });

    expect(summary).toContain('порог $250.00');
  });
});
