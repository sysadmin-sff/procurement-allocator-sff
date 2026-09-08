import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ErrorBanner } from './ErrorBanner';
import { ApiError } from '../api/client';

describe('ErrorBanner', () => {
  it('renders nothing when error is null', () => {
    const { container } = render(<ErrorBanner error={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the ApiError detail string when present', () => {
    render(<ErrorBanner error={new ApiError(400, { detail: 'Bad input' })} />);
    expect(screen.getByText('Bad input')).toBeInTheDocument();
  });

  it('shows conflictMessage for a 409 ApiError when provided', () => {
    render(
      <ErrorBanner
        error={new ApiError(409, { detail: 'conflict' })}
        conflictMessage="Нельзя удалить — есть связанные записи."
      />,
    );
    expect(screen.getByText('Нельзя удалить — есть связанные записи.')).toBeInTheDocument();
  });

  it('shows a friendly Russian message for a raw fetch network failure, not the browser TypeError text', () => {
    render(<ErrorBanner error={new TypeError('Failed to fetch')} />);
    expect(screen.queryByText('Failed to fetch')).not.toBeInTheDocument();
    expect(screen.getByText(/Не удалось связаться с сервером/)).toBeInTheDocument();
  });

  it('falls back to a generic message for an unrecognized non-Error value', () => {
    render(<ErrorBanner error={'some unexpected thrown value'} />);
    expect(screen.getByText('Неизвестная ошибка. Попробуйте ещё раз.')).toBeInTheDocument();
  });
});
