import { http } from './client';
import type { Order, OrderItem } from './types';

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
};
