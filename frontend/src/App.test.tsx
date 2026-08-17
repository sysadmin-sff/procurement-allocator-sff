import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import App from './App';
import { projectsApi } from './api/projects';

vi.mock('./api/projects', () => ({
  projectsApi: { list: vi.fn(), create: vi.fn(), get: vi.fn(), addItem: vi.fn() },
}));

vi.mocked(projectsApi.list).mockResolvedValue([]);

describe('App', () => {
  it('renders the nav and redirects / to the projects list', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByText('SCREEN FACTORY')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Проекты' })).toBeInTheDocument();
  });
});
