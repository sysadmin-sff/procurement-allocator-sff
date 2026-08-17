import { http } from './client';
import type { Project, ProjectCreate, ProjectItem, ProjectItemCreate, ProjectWithItems } from './types';

export const projectsApi = {
  list: () => http.get<Project[]>('/projects'),
  create: (payload: ProjectCreate) => http.post<Project>('/projects', payload),
  get: (id: string) => http.get<ProjectWithItems>(`/projects/${id}`),
  addItem: (projectId: string, payload: ProjectItemCreate) =>
    http.post<ProjectItem>(`/projects/${projectId}/items`, payload),
  updateItem: (projectId: string, itemId: string, quantity: number) =>
    http.patch<ProjectItem>(`/projects/${projectId}/items/${itemId}`, { quantity }),
  removeItem: (projectId: string, itemId: string) =>
    http.delete<void>(`/projects/${projectId}/items/${itemId}`),
};
