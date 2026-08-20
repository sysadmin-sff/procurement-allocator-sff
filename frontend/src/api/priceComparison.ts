import { http } from './client';
import type { PriceComparisonOut } from './types';

export const priceComparisonApi = {
  get: (projectId: string) =>
    http.get<PriceComparisonOut>(`/projects/${projectId}/price-comparison`),
};
