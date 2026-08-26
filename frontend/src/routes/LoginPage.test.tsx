import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LoginPage } from './LoginPage';
import { BASE_URL } from '../api/client';

describe('LoginPage', () => {
  it('renders a plain link (not a button) to GET /auth/login on the backend', () => {
    render(<LoginPage />);

    const link = screen.getByRole('link', { name: /войти через google/i });
    expect(link).toHaveAttribute('href', `${BASE_URL}/auth/login`);
  });
});
