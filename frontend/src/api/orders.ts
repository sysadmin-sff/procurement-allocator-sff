import { http } from './client';
import type { FindReplacementResult, Order, OrderItem } from './types';

export interface OrderItemPatch {
  confirmed_price?: number | null;
  received_price?: number | null;
  declined?: boolean;
  decline_reason?: string | null;
}

export const ordersApi = {
  createForRun: (projectId: string, runId: string, replaceDrafts = false) =>
    http.post<Order[]>(`/projects/${projectId}/allocations/${runId}/orders`, {
      replace_drafts: replaceDrafts,
    }),
  listForProject: (projectId: string) => http.get<Order[]>(`/projects/${projectId}/orders`),
  get: (orderId: string) => http.get<Order>(`/orders/${orderId}`),
  patchItem: (orderId: string, itemId: string, patch: OrderItemPatch) =>
    http.patch<OrderItem>(`/orders/${orderId}/items/${itemId}`, patch),
  findReplacement: (orderId: string, itemId: string) =>
    http.post<FindReplacementResult>(`/orders/${orderId}/items/${itemId}/find-replacement`, undefined),
  /** POST .../replace-and-order — see ADR-0015. One call: overrides the
   * AllocationLine to supplier_id and syncs the target draft Order
   * (creates it or adds an OrderItem to the existing one), replacing the
   * old allocationApi.overrideLine + projectsApi.get(run_id) combo. */
  replaceAndOrder: (orderId: string, itemId: string, supplierId: string) =>
    http.post<OrderItem>(`/orders/${orderId}/items/${itemId}/replace-and-order`, {
      supplier_id: supplierId,
    }),
};
