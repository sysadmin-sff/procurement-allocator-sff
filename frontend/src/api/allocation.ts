import { http } from './client';
import type { AllocationRun } from './types';

export const allocationApi = {
  run: (projectId: string) =>
    http.post<AllocationRun>(`/projects/${projectId}/allocate`, undefined),
  get: (projectId: string, runId: string) =>
    http.get<AllocationRun>(`/projects/${projectId}/allocations/${runId}`),
};
