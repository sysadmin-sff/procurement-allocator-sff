import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { UsersPage } from './UsersPage';
import { usersApi } from '../api/users';
import { ApiError } from '../api/client';
import { AuthContext } from '../auth/AuthContext';
import type { CurrentUser, User } from '../api/types';

vi.mock('../api/users', () => ({
  usersApi: { list: vi.fn(), create: vi.fn(), update: vi.fn() },
}));

const users: User[] = [
  {
    id: 'u1',
    email: 'jane@screen-factory-florida.com',
    name: 'Jane Doe',
    role: 'admin',
    is_active: true,
    created_at: '2026-01-10T12:00:00Z',
    last_login_at: '2026-08-20T09:30:00Z',
  },
  {
    id: 'u2',
    email: 'new-hire@screen-factory-florida.com',
    name: null,
    role: 'employee',
    is_active: true,
    created_at: '2026-08-01T00:00:00Z',
    last_login_at: null,
  },
];

function renderAs(role: CurrentUser['role']) {
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={{ id: 'u1', email: 'a@b.com', name: 'A', role }}>
        <UsersPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe('UsersPage', () => {
  it('renders the user list with role, status and last login', async () => {
    vi.mocked(usersApi.list).mockResolvedValue(users);
    renderAs('admin');

    expect(await screen.findByText('jane@screen-factory-florida.com')).toBeInTheDocument();
    expect(screen.getByText('new-hire@screen-factory-florida.com')).toBeInTheDocument();
    expect(screen.getByText('Ещё не входил')).toBeInTheDocument();
    expect(screen.getAllByText('Активен').length).toBeGreaterThan(0);
  });

  it('disables add/edit/toggle actions for employee role', async () => {
    vi.mocked(usersApi.list).mockResolvedValue(users);
    renderAs('employee');

    expect(await screen.findByText('jane@screen-factory-florida.com')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /добавить пользователя/i })).toBeDisabled();
    expect(screen.getAllByRole('button', { name: /изменить роль/i })[0]).toBeDisabled();
    expect(screen.getAllByRole('button', { name: /отключить|активировать/i })[0]).toBeDisabled();
  });

  it('creates a new user via the form', async () => {
    vi.mocked(usersApi.list).mockResolvedValue(users);
    vi.mocked(usersApi.create).mockResolvedValue({
      id: 'u3',
      email: 'created@screen-factory-florida.com',
      name: null,
      role: 'employee',
      is_active: true,
      created_at: '2026-08-27T00:00:00Z',
      last_login_at: null,
    });
    const user = userEvent.setup();
    renderAs('admin');

    await screen.findByText('jane@screen-factory-florida.com');
    await user.click(screen.getByRole('button', { name: /добавить пользователя/i }));
    await user.type(screen.getByLabelText(/email/i), 'created@screen-factory-florida.com');
    await user.click(screen.getByRole('button', { name: /^добавить пользователя$/i }));

    expect(usersApi.create).toHaveBeenCalledWith({
      email: 'created@screen-factory-florida.com',
      role: 'employee',
    });
  });

  it('shows a clear message when deactivating the last admin returns 409', async () => {
    vi.mocked(usersApi.list).mockResolvedValue(users);
    vi.mocked(usersApi.update).mockRejectedValue(
      new ApiError(409, { detail: 'Cannot deactivate the last active admin' }),
    );
    const user = userEvent.setup();
    renderAs('admin');

    await screen.findByText('jane@screen-factory-florida.com');
    await user.click(screen.getAllByRole('button', { name: /отключить/i })[0]);

    expect(
      await screen.findByText('Нельзя деактивировать единственного администратора.'),
    ).toBeInTheDocument();
  });

  it('shows an insufficient-permissions message on 403 instead of crashing', async () => {
    vi.mocked(usersApi.list).mockRejectedValue(new ApiError(403, { detail: 'Forbidden' }));
    renderAs('employee');

    expect(await screen.findByText('Недостаточно прав')).toBeInTheDocument();
  });
});
