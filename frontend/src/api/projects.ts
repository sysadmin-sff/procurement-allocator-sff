import { http } from './client';
import type { Project, ProjectCreate, ProjectItem, ProjectItemCreate, ProjectWithItems } from './types';

export const projectsApi = {
  list: () => http.get<Project[]>('/projects'),
  create: (payload: ProjectCreate) => http.post<Project>('/projects', payload),
  /** color_choice omitted (not undefined) leaves it untouched server-side;
   * pass null explicitly to clear it. title is always required by the
   * backend's ProjectUpdate schema, even when only color_choice changed. */
  updateProject: (id: string, title: string, colorChoice?: string | null) =>
    http.patch<Project>(
      `/projects/${id}`,
      colorChoice === undefined ? { title } : { title, color_choice: colorChoice },
    ),
  get: (id: string) => http.get<ProjectWithItems>(`/projects/${id}`),
  addItem: (projectId: string, payload: ProjectItemCreate) =>
    http.post<ProjectItem>(`/projects/${projectId}/items`, payload),
  updateItem: (projectId: string, itemId: string, quantity: number) =>
    http.patch<ProjectItem>(`/projects/${projectId}/items/${itemId}`, { quantity }),
  removeItem: (projectId: string, itemId: string) =>
    http.delete<void>(`/projects/${projectId}/items/${itemId}`),
  remove: (id: string) => http.delete<void>(`/projects/${id}`),
  complete: (id: string) => http.post<Project>(`/projects/${id}/complete`, {}),
};
