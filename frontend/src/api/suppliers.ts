import { diff, http } from './client';
import type { Supplier, SupplierCreate } from './types';

export const suppliersApi = {
  list: () => http.get<Supplier[]>('/suppliers'),
  get: (id: string) => http.get<Supplier>(`/suppliers/${id}`),
  create: (payload: SupplierCreate) => http.post<Supplier>('/suppliers', payload),
  /** Sends only fields changed between `before` and `after` (PATCH-via-PUT semantics). */
  update: (id: string, before: Supplier, after: Supplier) =>
    http.put<Supplier>(`/suppliers/${id}`, diff(before, after)),
  remove: (id: string) => http.delete<void>(`/suppliers/${id}`),
};
