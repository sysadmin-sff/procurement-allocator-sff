import { http } from './client';
import type { AllocationLine, AllocationRun } from './types';

export const allocationApi = {
  run: (projectId: string) =>
    http.post<AllocationRun>(`/projects/${projectId}/allocate`, undefined),
  get: (projectId: string, runId: string) =>
    http.get<AllocationRun>(`/projects/${projectId}/allocations/${runId}`),
  overrideLine: (
    projectId: string,
    runId: string,
    lineId: string,
    supplierId: string,
    sourceOrderItemId?: string,
  ) =>
    http.patch<AllocationLine>(
      `/projects/${projectId}/allocations/${runId}/lines/${lineId}`,
      { supplier_id: supplierId, source_order_item_id: sourceOrderItemId ?? null },
    ),
};
