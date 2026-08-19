import { diff, http } from './client';
import type {
  Office,
  OfficeCreate,
  Supplier,
  SupplierContact,
  SupplierContactCreate,
  SupplierCreate,
  SupplierDetail,
} from './types';

export const suppliersApi = {
  list: () => http.get<Supplier[]>('/suppliers'),
  get: (id: string) => http.get<SupplierDetail>(`/suppliers/${id}`),
  create: (payload: SupplierCreate) => http.post<Supplier>('/suppliers', payload),
  /** Sends only fields changed between `before` and `after` (PATCH-via-PUT semantics). */
  update: (id: string, before: Supplier, after: Supplier) =>
    http.put<Supplier>(`/suppliers/${id}`, diff(before, after)),
  remove: (id: string) => http.delete<void>(`/suppliers/${id}`),

  createOffice: (supplierId: string, payload: OfficeCreate) =>
    http.post<Office>(`/suppliers/${supplierId}/offices`, payload),
  updateOffice: (supplierId: string, officeId: string, before: Office, after: Office) =>
    http.patch<Office>(`/suppliers/${supplierId}/offices/${officeId}`, diff(before, after)),
  removeOffice: (supplierId: string, officeId: string) =>
    http.delete<void>(`/suppliers/${supplierId}/offices/${officeId}`),

  createContact: (supplierId: string, payload: SupplierContactCreate) =>
    http.post<SupplierContact>(`/suppliers/${supplierId}/contacts`, payload),
  updateContact: (
    supplierId: string,
    contactId: string,
    before: SupplierContact,
    after: SupplierContact,
  ) =>
    http.patch<SupplierContact>(
      `/suppliers/${supplierId}/contacts/${contactId}`,
      diff(before, after),
    ),
  removeContact: (supplierId: string, contactId: string) =>
    http.delete<void>(`/suppliers/${supplierId}/contacts/${contactId}`),
};
