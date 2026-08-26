import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { MaterialsPage } from './MaterialsPage';
import { materialsApi } from '../api/materials';
import { suppliersApi } from '../api/suppliers';
import { AuthContext } from '../auth/AuthContext';
import type { CurrentUser, Material } from '../api/types';

vi.mock('../api/materials', () => ({
  materialsApi: { list: vi.fn(), search: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('../api/suppliers', () => ({
  suppliersApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const materials: Material[] = [
  {
    id: 'm1',
    internal_sku: 'SKU-1',
    canonical_name: 'Screen mesh',
    category: null,
    unit: 'roll',
    attributes: {},
  },
];

function renderAs(role: CurrentUser['role']) {
  vi.mocked(materialsApi.list).mockResolvedValue(materials);
  vi.mocked(suppliersApi.list).mockResolvedValue([]);
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
});
