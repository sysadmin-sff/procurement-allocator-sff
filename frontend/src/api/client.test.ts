import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, diff, http } from './client';

describe('ApiError', () => {
  it('exposes the full response body, not just its detail field', () => {
    const body = {
      detail: 'draft_orders_exist',
      suppliers_with_existing_drafts: [{ supplier_id: 's1', supplier_name: 'ABC' }],
    };

    const error = new ApiError(409, body);

    expect(error.body).toEqual(body);
  });
});

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

describe('http credentials and CSRF (ADR-0024 §7)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => undefined,
    });
    vi.stubGlobal('fetch', fetchMock);
    document.cookie = 'csrf_token=abc123; path=/';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.cookie = 'csrf_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
  });

  it('sends credentials: include on GET requests', async () => {
    await http.get('/materials');

    const init = fetchMock.mock.calls[0][1];
    expect(init.credentials).toBe('include');
  });

  it('does not send X-CSRF-Token on GET requests', async () => {
    await http.get('/materials');

    const init = fetchMock.mock.calls[0][1];
    expect(init.headers['X-CSRF-Token']).toBeUndefined();
  });

  it('sends credentials: include and X-CSRF-Token on POST requests', async () => {
    await http.post('/materials', { name: 'foo' });

    const init = fetchMock.mock.calls[0][1];
    expect(init.credentials).toBe('include');
    expect(init.headers['X-CSRF-Token']).toBe('abc123');
  });

  it('sends X-CSRF-Token on PUT requests', async () => {
    await http.put('/materials/1', { name: 'foo' });
    expect(fetchMock.mock.calls[0][1].headers['X-CSRF-Token']).toBe('abc123');
  });

  it('sends X-CSRF-Token on PATCH requests', async () => {
    await http.patch('/materials/1', { name: 'foo' });
    expect(fetchMock.mock.calls[0][1].headers['X-CSRF-Token']).toBe('abc123');
  });

  it('sends X-CSRF-Token on DELETE requests', async () => {
    await http.delete('/materials/1');
    expect(fetchMock.mock.calls[0][1].headers['X-CSRF-Token']).toBe('abc123');
  });

  it('sends credentials: include and X-CSRF-Token on postMultipart requests', async () => {
    await http.postMultipart('/suppliers/1/price-lists', new FormData());

    const init = fetchMock.mock.calls[0][1];
    expect(init.credentials).toBe('include');
    expect(init.headers['X-CSRF-Token']).toBe('abc123');
  });
});
