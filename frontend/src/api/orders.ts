import { http } from './client';
import type {
  ConfirmPriceUpdatesOut,
  FindReplacementResult,
  Order,
  OrderItem,
  ParseOrderResponseResult,
  PriceUpdateSelection,
} from './types';

export interface OrderItemPatch {
  confirmed_price?: number | null;
  received_price?: number | null;
  target_price?: number | null;
  declined?: boolean;
  decline_reason?: string | null;
}

export const ordersApi = {
  /** acknowledgeConflict — "Создать дополнительно" (ADR-0012 §1/§2): caller
   * already saw the 409 and wants the extra Order anyway, without deleting
   * the existing drafts. Distinct from replaceDrafts=false — the endpoint
   * is stateless and can't otherwise tell "not asked yet" from "asked and
   * confirmed". See docs/known-issues.md "Follow-up... дозаказ тому же
   * поставщику". replaceDrafts takes precedence if both are true. */
  createForRun: (projectId: string, runId: string, replaceDrafts = false, acknowledgeConflict = false) =>
    http.post<Order[]>(`/projects/${projectId}/allocations/${runId}/orders`, {
      replace_drafts: replaceDrafts,
      acknowledge_conflict: acknowledgeConflict,
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
  /** POST .../parse-response — see ADR-0018 §3. Read-only preview, writes
   * nothing server-side; the file is never persisted (ADR-0018 §7). */
  parseResponse: (orderId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return http.postMultipart<ParseOrderResponseResult>(`/orders/${orderId}/parse-response`, formData);
  },
  /** POST .../confirm-price-updates — see ADR-0030 п.4.3. Used both by the
   * single-row popup (one selection) and the batch screen (one per divergent
   * row) — same endpoint, not two API paths. */
  confirmPriceUpdates: (orderId: string, selections: PriceUpdateSelection[]) =>
    http.post<ConfirmPriceUpdatesOut>(`/orders/${orderId}/confirm-price-updates`, { selections }),
};
