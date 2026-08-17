import { diff, http } from './client';
import type { Price, PriceCreate, PriceUpdate } from './types';

export interface PriceListFilter {
  material_id?: string;
  supplier_id?: string;
}

export const pricesApi = {
  list: (filter: PriceListFilter = {}) => {
    const params = new URLSearchParams();
    if (filter.material_id) params.set('material_id', filter.material_id);
    if (filter.supplier_id) params.set('supplier_id', filter.supplier_id);
    const query = params.toString();
    return http.get<Price[]>(`/prices${query ? `?${query}` : ''}`);
  },
  get: (id: string) => http.get<Price>(`/prices/${id}`),
  create: (payload: PriceCreate) => http.post<Price>('/prices', payload),
  /**
   * Price rows are immutable and versioned server-side: PUT closes the
   * current row and creates a new one. `valid_from` is required on every
   * call (the new row's start date has no default) and is passed through
   * as-is; other fields are diffed against `before` so unrelated fields
   * inherit from the row being closed instead of being resent.
   */
  update: (id: string, before: Price, after: Price & { valid_from: string }) => {
    const changed = diff(before, after);
    const payload: PriceUpdate = { ...changed, valid_from: after.valid_from };
    return http.put<Price>(`/prices/${id}`, payload);
  },
  remove: (id: string) => http.delete<void>(`/prices/${id}`),
};
