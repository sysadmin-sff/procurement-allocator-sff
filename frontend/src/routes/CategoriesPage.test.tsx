import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { CategoriesPage } from './CategoriesPage';
import { categoriesApi } from '../api/categories';
import { ApiError } from '../api/client';
import { AuthContext } from '../auth/AuthContext';
import type { Category, CurrentUser } from '../api/types';

vi.mock('../api/categories', () => ({
  categoriesApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const categories: Category[] = [
  {
    id: 'c1',
    name: 'Doors',
    sku_prefix: 'DOOR',
    requires_single_supplier: true,
    next_sku_number: 27,
    created_at: '2026-01-10T12:00:00Z',
  },
  {
    id: 'c2',
    name: 'Connectors',
    sku_prefix: 'CONN',
    requires_single_supplier: false,
    next_sku_number: 310,
    created_at: '2026-01-10T12:00:00Z',
  },
];

function renderAs(role: CurrentUser['role']) {
  vi.mocked(categoriesApi.list).mockResolvedValue(categories);
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={{ id: 'u1', email: 'a@b.com', name: 'A', role }}>
        <CategoriesPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe('CategoriesPage', () => {
  it('renders the category list with sku_prefix and requires_single_supplier', async () => {
    renderAs('admin');

    expect(await screen.findByText('Doors')).toBeInTheDocument();
    expect(screen.getByText('DOOR')).toBeInTheDocument();
    expect(screen.getByText('Connectors')).toBeInTheDocument();
    expect(screen.getByText('CONN')).toBeInTheDocument();
  });

  it('disables add/edit/delete actions for employee role', async () => {
    renderAs('employee');

    expect(await screen.findByText('Doors')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /добавить категорию/i })).toBeDisabled();
    expect(screen.getAllByRole('button', { name: /переименовать/i })[0]).toBeDisabled();
    expect(screen.getAllByRole('button', { name: /удалить/i })[0]).toBeDisabled();
  });

  it('creates a new category via the form, sku_prefix included only on create', async () => {
    vi.mocked(categoriesApi.create).mockResolvedValue({
      id: 'c3',
      name: 'Caulk 2',
      sku_prefix: 'CAUL2',
      requires_single_supplier: false,
      next_sku_number: 1,
      created_at: '2026-09-16T00:00:00Z',
    });
    const user = userEvent.setup();
    renderAs('admin');

    await screen.findByText('Doors');
    await user.click(screen.getByRole('button', { name: /добавить категорию/i }));
    await user.type(screen.getByLabelText(/^название$/i), 'Caulk 2');
    await user.type(screen.getByLabelText(/sku[_-]?prefix/i), 'CAUL2');
    await user.click(screen.getByRole('button', { name: /^добавить категорию$/i }));

    expect(categoriesApi.create).toHaveBeenCalledWith({
      name: 'Caulk 2',
      sku_prefix: 'CAUL2',
      requires_single_supplier: false,
    });
  });

  it('warns that sku_prefix cannot be changed once a category exists', async () => {
    const user = userEvent.setup();
    renderAs('admin');

    await screen.findByText('Doors');
    await user.click(screen.getByRole('button', { name: /добавить категорию/i }));

    expect(
      screen.getByText(/sku_prefix.*(нельзя изменить|неизменяем)/i),
    ).toBeInTheDocument();
  });

  it('renames a category', async () => {
    vi.mocked(categoriesApi.update).mockResolvedValue({
      ...categories[0],
      name: 'Doors Renamed',
    });
    const user = userEvent.setup();
    renderAs('admin');

    await screen.findByText('Doors');
    await user.click(screen.getAllByRole('button', { name: /переименовать/i })[0]);
    const nameInput = screen.getByDisplayValue('Doors');
    await user.clear(nameInput);
    await user.type(nameInput, 'Doors Renamed');
    await user.click(screen.getByRole('button', { name: /сохранить/i }));

    expect(categoriesApi.update).toHaveBeenCalledWith('c1', { name: 'Doors Renamed' });
  });

  it('toggles requires_single_supplier via checkbox', async () => {
    vi.mocked(categoriesApi.update).mockResolvedValue({
      ...categories[1],
      requires_single_supplier: true,
    });
    const user = userEvent.setup();
    renderAs('admin');

    await screen.findByText('Connectors');
    const checkboxes = screen.getAllByRole('checkbox');
    // c2 (Connectors) is the second row, requires_single_supplier=false initially.
    await user.click(checkboxes[1]);

    expect(categoriesApi.update).toHaveBeenCalledWith('c2', { requires_single_supplier: true });
  });

  it('deletes an empty category successfully', async () => {
    vi.mocked(categoriesApi.remove).mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderAs('admin');

    await screen.findByText('Doors');
    await user.click(screen.getAllByRole('button', { name: /удалить/i })[0]);
    await user.click(screen.getByRole('button', { name: /^да$/i }));

    expect(categoriesApi.remove).toHaveBeenCalledWith('c1');
  });

  it('shows the backend 409 message verbatim when deleting a category in use', async () => {
    vi.mocked(categoriesApi.remove).mockRejectedValue(
      new ApiError(409, { detail: 'Category is referenced by 26 material(s), cannot delete' }),
    );
    const user = userEvent.setup();
    renderAs('admin');

    await screen.findByText('Doors');
    await user.click(screen.getAllByRole('button', { name: /удалить/i })[0]);
    await user.click(screen.getByRole('button', { name: /^да$/i }));

    expect(
      await screen.findByText('Category is referenced by 26 material(s), cannot delete'),
    ).toBeInTheDocument();
  });
});
