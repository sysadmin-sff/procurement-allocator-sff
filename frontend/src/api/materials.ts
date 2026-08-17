import { diff, http } from './client';
import type { Material, MaterialCreate } from './types';

export const materialsApi = {
  list: () => http.get<Material[]>('/materials'),
  search: (q: string) => http.get<Material[]>(`/materials/search?q=${encodeURIComponent(q)}`),
  get: (id: string) => http.get<Material>(`/materials/${id}`),
  create: (payload: MaterialCreate) => http.post<Material>('/materials', payload),
  /** Sends only fields changed between `before` and `after` (PATCH-via-PUT semantics). */
  update: (id: string, before: Material, after: Material) =>
    http.put<Material>(`/materials/${id}`, diff(before, after)),
  remove: (id: string) => http.delete<void>(`/materials/${id}`),
};
