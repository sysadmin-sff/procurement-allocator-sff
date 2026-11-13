import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AppLayout } from './AppLayout';
import { authApi } from '../api/auth';
import { AuthContext } from '../auth/AuthContext';
import type { CurrentUser } from '../api/types';

vi.mock('../api/auth', () => ({
  authApi: { me: vi.fn(), logout: vi.fn() },
}));

const logoutMock = vi.mocked(authApi.logout);

function renderLayout(user: CurrentUser) {
  return render(
    <MemoryRouter initialEntries={['/projects']}>
      <AuthContext.Provider value={user}>
        <Routes>
          <Route path="/login" element={<div>Страница входа</div>} />
          <Route path="/projects" element={<AppLayout />}>
            <Route index element={<div>Список проектов</div>} />
          </Route>
        </Routes>
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe('AppLayout', () => {
  it('shows the current user name/email from context', () => {
    renderLayout({ id: 'u1', email: 'jane@screen-factory-florida.com', name: 'Jane Doe', role: 'employee' });

    expect(screen.getByText('Jane Doe')).toBeInTheDocument();
    expect(screen.getByText('jane@screen-factory-florida.com')).toBeInTheDocument();
  });

  it('logs out and redirects to /login on click', async () => {
    logoutMock.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderLayout({ id: 'u1', email: 'jane@screen-factory-florida.com', name: 'Jane Doe', role: 'employee' });

    await user.click(screen.getByRole('button', { name: /выйти/i }));

    expect(logoutMock).toHaveBeenCalled();
    expect(await screen.findByText('Страница входа')).toBeInTheDocument();
  });

  // ADR-0055: employee works with projects, suppliers, materials and templates;
  // the price matrix, categories and users stay admin-only.
  it('shows the employee set of nav links and hides admin-only ones for employee role', () => {
    renderLayout({ id: 'u1', email: 'jane@screen-factory-florida.com', name: 'Jane Doe', role: 'employee' });

    expect(screen.getByRole('link', { name: /проекты/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /поставщики/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /материалы/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /шаблоны/i })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /^цены$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /категории/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /пользователи/i })).not.toBeInTheDocument();
  });

  it('shows every nav link for admin role', () => {
    renderLayout({ id: 'u1', email: 'admin@screen-factory-florida.com', name: 'Admin', role: 'admin' });

    for (const name of [/проекты/i, /поставщики/i, /материалы/i, /^цены$/i, /категории/i, /шаблоны/i, /пользователи/i]) {
      expect(screen.getByRole('link', { name })).toBeInTheDocument();
    }
  });
});
