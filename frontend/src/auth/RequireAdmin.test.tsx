import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AuthContext } from './AuthContext';
import { RequireAdmin } from './RequireAdmin';

function renderAs(role: 'admin' | 'employee') {
  return render(
    <MemoryRouter initialEntries={['/prices']}>
      <AuthContext.Provider value={{ id: 'u1', email: 'a@b.com', name: 'A', role }}>
        <Routes>
          <Route path="/projects" element={<div>Проекты-экран</div>} />
          <Route
            path="/prices"
            element={
              <RequireAdmin>
                <div>Админ-экран</div>
              </RequireAdmin>
            }
          />
        </Routes>
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe('RequireAdmin (ADR-0055)', () => {
  it('renders the screen for admin', () => {
    renderAs('admin');
    expect(screen.getByText('Админ-экран')).toBeInTheDocument();
  });

  it('redirects an employee to the projects list', () => {
    renderAs('employee');
    expect(screen.getByText('Проекты-экран')).toBeInTheDocument();
    expect(screen.queryByText('Админ-экран')).not.toBeInTheDocument();
  });
});
