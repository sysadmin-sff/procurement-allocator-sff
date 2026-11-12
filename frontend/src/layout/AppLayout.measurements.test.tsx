import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AppLayout } from './AppLayout';
import { ApiError } from '../api/client';
import { measurementsApi } from '../api/measurements';
import { AuthContext } from '../auth/AuthContext';
import type { CurrentUser } from '../api/types';

vi.mock('../api/auth', () => ({
  authApi: { me: vi.fn(), logout: vi.fn() },
}));
vi.mock('../api/measurements', () => ({
  measurementsApi: { access: vi.fn() },
}));

const accessMock = vi.mocked(measurementsApi.access);

const employee: CurrentUser = {
  id: 'u1',
  email: 'jane@screen-factory-florida.com',
  name: 'Jane Doe',
  role: 'employee',
};

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/projects']}>
      <AuthContext.Provider value={employee}>
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

describe('AppLayout — пункт «Замеры» (ADR-0051 §2)', () => {
  beforeEach(() => {
    accessMock.mockReset();
  });

  it('shows the item when /measurements/access answers 200, also for an employee', async () => {
    accessMock.mockResolvedValue({ access: true });

    renderLayout();

    const link = await screen.findByRole('link', { name: 'Замеры' });
    expect(link).toHaveAttribute('href', '/measurements');
  });

  it.each([
    ['403', () => new ApiError(403, { detail: 'Insufficient permissions' })],
    ['404', () => new ApiError(404, { detail: 'Not Found' })],
    ['401', () => new ApiError(401, { detail: 'Not authenticated' })],
    ['a network error', () => new TypeError('Failed to fetch')],
  ])('hides the item silently on %s and keeps the layout', async (_name, makeError) => {
    accessMock.mockRejectedValue(makeError());

    renderLayout();

    await waitFor(() => expect(accessMock).toHaveBeenCalledTimes(1));
    // Let the rejection settle before asserting the item stayed hidden.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole('link', { name: 'Замеры' })).not.toBeInTheDocument();
    expect(screen.getByText('Jane Doe')).toBeInTheDocument();
    expect(screen.getByText('Список проектов')).toBeInTheDocument();
    expect(screen.queryByText('Страница входа')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not break when the request throws synchronously', async () => {
    accessMock.mockImplementation(() => {
      throw new Error('boom');
    });

    renderLayout();

    await waitFor(() => expect(accessMock).toHaveBeenCalledTimes(1));
    expect(screen.getByText('Список проектов')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Замеры' })).not.toBeInTheDocument();
  });
});
