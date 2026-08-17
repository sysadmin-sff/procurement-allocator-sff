import { describe, expect, it } from 'vitest';
import { diff } from './client';

describe('diff', () => {
  it('omits unchanged top-level fields', () => {
    const before = { name: 'Alutex', currency: 'USD' };
    const after = { name: 'Alutex Supply', currency: 'USD' };

    expect(diff(before, after)).toEqual({ name: 'Alutex Supply' });
  });

  it('preserves an explicit null vs 0 distinction on nested fields (ADR-0002)', () => {
    const before = {
      delivery_policy: { flat_fee: 15, free_shipping_threshold: null as number | null },
    };
    const afterUnsetToZero = {
      delivery_policy: { flat_fee: 15, free_shipping_threshold: 0 },
    };
    const afterZeroToUnset = {
      delivery_policy: { flat_fee: 15, free_shipping_threshold: null as number | null },
    };

    expect(diff(before, afterUnsetToZero)).toEqual({
      delivery_policy: { flat_fee: 15, free_shipping_threshold: 0 },
    });
    expect(diff(afterUnsetToZero, afterZeroToUnset)).toEqual({
      delivery_policy: { flat_fee: 15, free_shipping_threshold: null },
    });
  });

  it('does not send nested fields the user left untouched', () => {
    const before = {
      delivery_policy: { flat_fee: 15, free_shipping_threshold: 250, lead_time_days: 3 },
    };
    const after = {
      delivery_policy: { flat_fee: 20, free_shipping_threshold: 250, lead_time_days: 3 },
    };

    expect(diff(before, after)).toEqual({
      delivery_policy: { flat_fee: 20, free_shipping_threshold: 250, lead_time_days: 3 },
    });
  });

  it('returns an empty object when nothing changed', () => {
    const before = { name: 'Alutex' };
    const after = { name: 'Alutex' };

    expect(diff(before, after)).toEqual({});
  });
});
