import { http } from './client';
import type { ApplyPriceListEntryIn, PriceListEntry, PriceListImport } from './types';

export const priceListImportsApi = {
  /** POST /suppliers/{id}/price-lists — multipart upload. Runs extraction +
   * matching synchronously and returns the full set of PriceListEntry for
   * the review screen. See ADR-0019 §5. */
  upload: (supplierId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return http.postMultipart<PriceListImport>(`/suppliers/${supplierId}/price-lists`, formData);
  },
  get: (importId: string) => http.get<PriceListImport>(`/price-list-imports/${importId}`),
  applyEntry: (importId: string, entryId: string, payload: ApplyPriceListEntryIn) =>
    http.post<PriceListEntry>(
      `/price-list-imports/${importId}/entries/${entryId}/apply`,
      payload,
    ),
};
