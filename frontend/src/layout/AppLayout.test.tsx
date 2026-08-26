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

  it('hides admin-only nav links (Поставщики/Материалы/Пользователи) for employee role', () => {
    renderLayout({ id: 'u1', email: 'jane@screen-factory-florida.com', name: 'Jane Doe', role: 'employee' });

    expect(screen.queryByRole('link', { name: /поставщики/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /материалы/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /пользователи/i })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /проекты/i })).toBeInTheDocument();
  });

  it('shows admin-only nav links (Поставщики/Материалы/Пользователи) for admin role', () => {
    renderLayout({ id: 'u1', email: 'admin@screen-factory-florida.com', name: 'Admin', role: 'admin' });

    expect(screen.getByRole('link', { name: /поставщики/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /материалы/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /пользователи/i })).toBeInTheDocument();
  });
});
