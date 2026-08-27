import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import App from './App';
import { authApi } from './api/auth';
import { projectsApi } from './api/projects';

vi.mock('./api/projects', () => ({
  projectsApi: { list: vi.fn(), create: vi.fn(), get: vi.fn(), addItem: vi.fn() },
}));
vi.mock('./api/auth', () => ({
  authApi: { me: vi.fn(), logout: vi.fn() },
}));

vi.mocked(projectsApi.list).mockResolvedValue([]);
vi.mocked(authApi.me).mockResolvedValue({
  id: 'u1',
  email: 'a@screen-factory-florida.com',
  name: 'Admin',
  role: 'admin',
});

describe('App', () => {
  it('renders the nav and redirects / to the projects list', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByAltText('Screen Factory Florida')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Проекты' })).toBeInTheDocument();
  });
});
