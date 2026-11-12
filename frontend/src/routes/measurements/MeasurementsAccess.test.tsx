import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../../App';
import { authApi } from '../../api/auth';
import { ApiError } from '../../api/client';
import { measurementsApi } from '../../api/measurements';

vi.mock('../../api/auth', () => ({
  authApi: { me: vi.fn(), logout: vi.fn() },
}));
vi.mock('../../api/measurements', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/measurements')>()),
  measurementsApi: { access: vi.fn(), metrics: vi.fn(), visits: vi.fn(), status: vi.fn() },
}));

const accessMock = vi.mocked(measurementsApi.access);
const metricsMock = vi.mocked(measurementsApi.metrics);
const visitsMock = vi.mocked(measurementsApi.visits);

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe('прямой заход в «Замеры» без доступа', () => {
  beforeEach(() => {
    vi.mocked(authApi.me).mockResolvedValue({
      id: 'u1',
      email: 'jane@screen-factory-florida.com',
      name: 'Jane Doe',
      role: 'employee',
    });
    accessMock.mockReset();
    metricsMock.mockReset();
    visitsMock.mockReset();
  });

  it('403 → «нет доступа к разделу», inside the app layout, no redirect', async () => {
    accessMock.mockRejectedValue(new ApiError(403, { detail: 'Insufficient permissions' }));
    metricsMock.mockRejectedValue(new ApiError(403, { detail: 'Insufficient permissions' }));

    renderAt('/measurements');

    expect(await screen.findByText(/нет доступа к разделу «Замеры»/i)).toBeInTheDocument();
    expect(screen.getByText('Jane Doe')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /повторить/i })).not.toBeInTheDocument();
  });

  it('404 → «раздел выключен»', async () => {
    accessMock.mockRejectedValue(new ApiError(404, { detail: 'Not Found' }));
    metricsMock.mockRejectedValue(new ApiError(404, { detail: 'Not Found' }));

    renderAt('/measurements');

    expect(await screen.findByText(/раздел «Замеры» выключен/i)).toBeInTheDocument();
  });

  it('the visits page shows the same messages', async () => {
    accessMock.mockRejectedValue(new ApiError(403, {}));
    visitsMock.mockRejectedValue(new ApiError(403, { detail: 'Insufficient permissions' }));

    renderAt('/measurements/visits?from=2026-10-01&to=2026-10-31');

    expect(await screen.findByText(/нет доступа к разделу «Замеры»/i)).toBeInTheDocument();
  });

  it('another error shows the message and a retry button', async () => {
    accessMock.mockResolvedValue({ access: true });
    metricsMock.mockRejectedValue(new ApiError(500, { detail: 'Internal Server Error' }));

    renderAt('/measurements');

    expect(await screen.findByText('Internal Server Error')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /повторить/i })).toBeInTheDocument();
  });
});
