import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { MaterialsPage } from './MaterialsPage';
import { materialsApi } from '../api/materials';
import { suppliersApi } from '../api/suppliers';
import { categoriesApi } from '../api/categories';
import { AuthContext } from '../auth/AuthContext';
import type { Category, CurrentUser, Material } from '../api/types';

vi.mock('../api/materials', () => ({
  materialsApi: { list: vi.fn(), search: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../api/suppliers', () => ({
  suppliersApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../api/categories', () => ({
  categoriesApi: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const materials: Material[] = [
  {
    id: 'm1',
    internal_sku: 'SKU-1',
    canonical_name: 'Screen mesh',
    category_name: 'Mesh',
    unit: 'roll',
    attributes: {},
  },
];

const categories: Category[] = [
  {
    id: 'cat-doors',
    name: 'Doors',
    sku_prefix: 'DOOR',
    requires_single_supplier: true,
    next_sku_number: 27,
    created_at: '2026-01-10T12:00:00Z',
  },
  {
    id: 'cat-mesh',
    name: 'Mesh',
    sku_prefix: 'MESH',
    requires_single_supplier: true,
    next_sku_number: 58,
    created_at: '2026-01-10T12:00:00Z',
  },
];

function renderAs(role: CurrentUser['role']) {
  vi.mocked(materialsApi.list).mockResolvedValue(materials);
  vi.mocked(suppliersApi.list).mockResolvedValue([]);
  vi.mocked(categoriesApi.list).mockResolvedValue(categories);
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={{ id: 'u1', email: 'a@b.com', name: 'A', role }}>
        <MaterialsPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe('MaterialsPage admin-only actions (ADR-0024 §7 — UI convenience only)', () => {
  it('disables add/edit/delete actions for employee role', async () => {
    renderAs('employee');

    expect(await screen.findByText('Screen mesh')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /добавить материал/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /изменить/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /удалить/i })).toBeDisabled();
  });

  it('enables add/edit/delete actions for admin role', async () => {
    renderAs('admin');

    expect(await screen.findByText('Screen mesh')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /добавить материал/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /изменить/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /удалить/i })).toBeEnabled();
  });

  it('shows category_name in the table', async () => {
    renderAs('admin');

    expect(await screen.findByText('Mesh')).toBeInTheDocument();
  });
});

describe('MaterialsPage — creating a material (ADR-0034)', () => {
  it('creates a material via a category select, without any internal_sku input, and shows the generated SKU', async () => {
    vi.mocked(materialsApi.create).mockResolvedValue({
      id: 'm2',
      internal_sku: 'DOOR-027',
      canonical_name: 'New door',
      category_name: 'Doors',
      unit: 'шт',
      attributes: {},
    });
    const user = userEvent.setup();
    renderAs('admin');

    await screen.findByText('Screen mesh');
    await user.click(screen.getByRole('button', { name: /добавить материал/i }));

    expect(screen.queryByLabelText(/internal_sku/i)).not.toBeInTheDocument();

    await user.type(screen.getByLabelText(/название/i), 'New door');
    await user.type(screen.getByLabelText(/единица измерения/i), 'шт');
    await user.selectOptions(screen.getByLabelText(/категория/i), 'cat-doors');
    await user.click(screen.getByRole('button', { name: /добавить материал/i }));

    expect(materialsApi.create).toHaveBeenCalledWith(
      expect.objectContaining({
        canonical_name: 'New door',
        category_id: 'cat-doors',
        unit: 'шт',
      }),
    );
    expect(materialsApi.create).not.toHaveBeenCalledWith(
      expect.objectContaining({ internal_sku: expect.anything() }),
    );

    expect(await screen.findByText(/DOOR-027/)).toBeInTheDocument();
  });
});
