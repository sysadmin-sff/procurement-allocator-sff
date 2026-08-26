import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { RequireAuth } from './RequireAuth';
import { authApi } from '../api/auth';
import { ApiError } from '../api/client';

vi.mock('../api/auth', () => ({
  authApi: { me: vi.fn(), logout: vi.fn() },
}));

const meMock = vi.mocked(authApi.me);

function renderGuarded() {
  return render(
    <MemoryRouter initialEntries={['/projects']}>
      <Routes>
        <Route path="/login" element={<div>Страница входа</div>} />
        <Route
          path="/projects"
          element={
            <RequireAuth>
              <div>Защищённый контент</div>
            </RequireAuth>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe('RequireAuth', () => {
  it('shows a loading state while /auth/me is pending', () => {
    meMock.mockReturnValue(new Promise(() => {}));

    renderGuarded();

    expect(screen.getByText(/загрузка/i)).toBeInTheDocument();
  });

  it('redirects to /login when /auth/me returns 401', async () => {
    meMock.mockRejectedValue(new ApiError(401, { detail: 'Not authenticated' }));

    renderGuarded();

    expect(await screen.findByText('Страница входа')).toBeInTheDocument();
  });

  it('renders children when /auth/me succeeds', async () => {
    meMock.mockResolvedValue({ id: 'u1', email: 'a@b.com', name: 'A', role: 'employee' });

    renderGuarded();

    expect(await screen.findByText('Защищённый контент')).toBeInTheDocument();
  });
});
