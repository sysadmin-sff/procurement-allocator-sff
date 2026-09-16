import { http } from './client';
import type { Category, CategoryCreate, CategoryUpdate } from './types';

export const categoriesApi = {
  list: () => http.get<Category[]>('/categories'),
  create: (payload: CategoryCreate) => http.post<Category>('/categories', payload),
  /** sku_prefix is immutable after creation (ADR-0034 п.5) — CategoryUpdate
   * has no such field, so callers can only ever send name/requires_single_supplier. */
  update: (id: string, payload: CategoryUpdate) => http.patch<Category>(`/categories/${id}`, payload),
  remove: (id: string) => http.delete<void>(`/categories/${id}`),
};
