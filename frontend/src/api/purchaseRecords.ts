import { http } from './client';
import type { PurchaseRecord, PurchaseRecordCreate, PurchaseRecordListOut, PurchaseRecordUpdate } from './types';

export const purchaseRecordsApi = {
  listForProject: (projectId: string) =>
    http.get<PurchaseRecordListOut>(`/projects/${projectId}/purchase-records`),
  create: (projectId: string, payload: PurchaseRecordCreate) =>
    http.post<PurchaseRecord>(`/projects/${projectId}/purchase-records`, payload),
  update: (projectId: string, recordId: string, payload: PurchaseRecordUpdate) =>
    http.patch<PurchaseRecord>(`/projects/${projectId}/purchase-records/${recordId}`, payload),
  remove: (projectId: string, recordId: string) =>
    http.delete<void>(`/projects/${projectId}/purchase-records/${recordId}`),
};
