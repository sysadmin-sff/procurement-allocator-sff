import { http } from './client';
import type { Order, OrderItem } from './types';

export const ordersApi = {
  createForRun: (projectId: string, runId: string) =>
    http.post<Order[]>(`/projects/${projectId}/allocations/${runId}/orders`, undefined),
  listForProject: (projectId: string) => http.get<Order[]>(`/projects/${projectId}/orders`),
  get: (orderId: string) => http.get<Order>(`/orders/${orderId}`),
  setConfirmedPrice: (orderId: string, itemId: string, confirmedPrice: number | null) =>
    http.patch<OrderItem>(`/orders/${orderId}/items/${itemId}`, {
      confirmed_price: confirmedPrice,
    }),
};
