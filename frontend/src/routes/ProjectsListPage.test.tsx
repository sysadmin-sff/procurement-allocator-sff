import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectsListPage } from './ProjectsListPage';
import { projectsApi } from '../api/projects';
import type { Project } from '../api/types';

vi.mock('../api/projects', () => ({
  projectsApi: { list: vi.fn(), create: vi.fn(), get: vi.fn(), addItem: vi.fn() },
}));

const listMock = vi.mocked(projectsApi.list);

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/projects']}>
      <Routes>
        <Route path="/projects" element={<ProjectsListPage />} />
        <Route path="/projects/new" element={<div>New project screen</div>} />
        <Route path="/projects/:projectId" element={<div>Project detail screen</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

const project: Project = {
  id: 'proj-1',
  title: 'Pool cage — Bayshore Rd',
  created_by: null,
  status: 'draft',
  created_at: '2026-08-17T00:00:00Z',
};

describe('ProjectsListPage', () => {
  beforeEach(() => {
    listMock.mockReset();
  });

  it('shows an empty state with a create action when there are no projects', async () => {
    listMock.mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText('Проектов пока нет')).toBeInTheDocument();
  });

  it('lists projects and navigates to the project detail screen on row click', async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue([project]);

    renderPage();

    const row = await screen.findByText(project.title);
    await user.click(row);

    expect(await screen.findByText('Project detail screen')).toBeInTheDocument();
  });

  it('navigates to the new project screen from the header button', async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue([]);

    renderPage();
    await screen.findByText('Проектов пока нет');

    await user.click(screen.getByRole('button', { name: /Новый проект/ }));

    expect(await screen.findByText('New project screen')).toBeInTheDocument();
  });
});
