import { beforeEach, describe, expect, it, vi } from 'vitest';
import { http } from './client';
import { measurementsApi } from './measurements';

vi.mock('./client', () => ({ http: { get: vi.fn() } }));

const getMock = vi.mocked(http.get);

describe('measurementsApi', () => {
  beforeEach(() => {
    getMock.mockReset();
    getMock.mockResolvedValue({});
  });

  it('omits unset parameters so the API applies its defaults', async () => {
    await measurementsApi.metrics({});
    expect(getMock).toHaveBeenCalledWith('/measurements/metrics');
  });

  it('encodes a measurer key with a space and passes group_by through', async () => {
    await measurementsApi.metrics({
      from: '2026-10-01',
      to: '2026-10-31',
      group_by: 'week',
      measurer: 'Matt Measurement',
    });
    const path = getMock.mock.calls[0][0];
    const query = new URLSearchParams(path.split('?')[1]);
    expect(path.startsWith('/measurements/metrics?')).toBe(true);
    expect(path).not.toContain(' ');
    expect(query.get('measurer')).toBe('Matt Measurement');
    expect(query.get('group_by')).toBe('week');
    expect(query.get('from')).toBe('2026-10-01');
    expect(query.get('to')).toBe('2026-10-31');
  });

  it('requests visits without a limit (the API default applies)', async () => {
    await measurementsApi.visits({ from: '2026-10-01', to: '2026-10-31', kind: 'additional' });
    expect(getMock).toHaveBeenCalledWith(
      '/measurements/metrics/visits?from=2026-10-01&to=2026-10-31&kind=additional',
    );
  });
});
