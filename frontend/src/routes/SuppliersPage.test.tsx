import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { SuppliersPage } from './SuppliersPage';
import { suppliersApi } from '../api/suppliers';
import { AuthContext } from '../auth/AuthContext';
import type { CurrentUser, Supplier } from '../api/types';

vi.mock('../api/suppliers', () => ({
  suppliersApi: { list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));

const suppliers: Supplier[] = [
  {
    id: 's1',
    name: 'Alutex',
    short_name: null,
    contacts: null,
    currency: 'USD',
    delivery_policy: { flat_fee: 0, free_shipping_threshold: null, per_order_min_amount: 0, lead_time_days: 1 },
    website: null,
    region: null,
    catalog_link: null,
    status: null,
    payment_terms: null,
    portal_url: null,
    comments: null,
  },
];

function renderAs(role: CurrentUser['role']) {
  vi.mocked(suppliersApi.list).mockResolvedValue(suppliers);
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={{ id: 'u1', email: 'a@b.com', name: 'A', role }}>
        <SuppliersPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe('SuppliersPage admin-only actions (ADR-0024 §7 — UI convenience only)', () => {
  it('disables add/delete actions for employee role', async () => {
    renderAs('employee');

    expect(await screen.findByText('Alutex')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /добавить поставщика/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /удалить/i })).toBeDisabled();
  });

  it('enables add/delete actions for admin role', async () => {
    renderAs('admin');

    expect(await screen.findByText('Alutex')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /добавить поставщика/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /удалить/i })).toBeEnabled();
  });
});
