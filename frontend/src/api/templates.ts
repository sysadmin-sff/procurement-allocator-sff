import { http } from './client';
import type { ProjectTemplate, ProjectTemplateCreate } from './types';

export const templatesApi = {
  list: () => http.get<ProjectTemplate[]>('/project-templates'),
  create: (payload: ProjectTemplateCreate) =>
    http.post<ProjectTemplate>('/project-templates', payload),
  rename: (id: string, name: string) =>
    http.patch<ProjectTemplate>(`/project-templates/${id}`, { name }),
  remove: (id: string) => http.delete<void>(`/project-templates/${id}`),
  addItem: (id: string, materialId: string) =>
    http.post<ProjectTemplate>(`/project-templates/${id}/items`, { material_id: materialId }),
  removeItem: (id: string, itemId: string) =>
    http.delete<ProjectTemplate>(`/project-templates/${id}/items/${itemId}`),
};
