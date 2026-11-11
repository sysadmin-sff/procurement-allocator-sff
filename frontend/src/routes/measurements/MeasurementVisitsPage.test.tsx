import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  MEASUREMENTS_VISITS_LIMIT_DEFAULT,
  measurementsApi,
  type MeasurementsVisitRow,
} from '../../api/measurements';
import { MATT } from './fixtures';
import { MeasurementVisitsPage } from './MeasurementVisitsPage';

vi.mock('../../api/measurements', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/measurements')>()),
  measurementsApi: { access: vi.fn(), metrics: vi.fn(), visits: vi.fn(), status: vi.fn() },
}));

const visitsMock = vi.mocked(measurementsApi.visits);

function row(overrides: Partial<MeasurementsVisitRow> = {}): MeasurementsVisitRow {
  return {
    task_id: 1,
    lead_id: 24681357,
    local_date: '2026-10-05',
    measurer_key: MATT,
    kind: 'additional',
    result_source: 'funnel',
    outcome: 'produced',
    is_completed: true,
    is_duplicate: false,
    ...overrides,
  };
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function renderPage(path: string, state?: unknown) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: path.split('?')[0], search: path.includes('?') ? `?${path.split('?')[1]}` : '', state }]}>
      <Routes>
        <Route path="/measurements/visits" element={<MeasurementVisitsPage />} />
        <Route path="/measurements" element={<div>Метрики</div>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe('MeasurementVisitsPage', () => {
  beforeEach(() => {
    visitsMock.mockReset();
  });

  it('requests exactly the URL parameters, a measurer with a space included, and no limit', async () => {
    visitsMock.mockResolvedValue([row()]);
    renderPage('/measurements/visits?from=2026-10-05&to=2026-10-11&measurer=Matt+Measurement&kind=additional');

    await screen.findByRole('table', { name: 'Замеры' });
    expect(visitsMock).toHaveBeenCalledWith({
      from: '2026-10-05',
      to: '2026-10-11',
      measurer: MATT,
      kind: 'additional',
    });
    expect(screen.getByText('05.10–11.10 · Matt Measurement · Доп. замер')).toBeInTheDocument();
  });

  it('renders a row with human-readable labels', async () => {
    visitsMock.mockResolvedValue([
      row(),
      row({
        task_id: 2,
        lead_id: 13572468,
        measurer_key: null,
        kind: 'primary',
        result_source: 'site_visit',
        outcome: null,
        is_completed: false,
        is_duplicate: true,
      }),
    ]);
    renderPage('/measurements/visits?from=2026-10-01&to=2026-10-31');

    const table = await screen.findByRole('table', { name: 'Замеры' });
    const [first, second] = within(table).getAllByRole('row').slice(1);
    expect(within(first).getAllByRole('cell').map((c) => c.textContent)).toEqual([
      '05.10.2026',
      MATT,
      'Доп. замер',
      'Воронка',
      'Передан в продажу',
      'Да',
      '—',
      '24681357Копировать',
    ]);
    expect(within(second).getAllByRole('cell').map((c) => c.textContent)).toEqual([
      '05.10.2026',
      'Без замерщика',
      'Замер',
      'Site Visit Result',
      '—',
      'Нет',
      'Дубль',
      '13572468Копировать',
    ]);
  });

  it('calls a legacy visit «Встреча» (amo task type 2)', async () => {
    visitsMock.mockResolvedValue([row({ kind: 'legacy' })]);
    renderPage('/measurements/visits?from=2026-11-01&to=2026-11-30&kind=legacy');

    const table = await screen.findByRole('table', { name: 'Замеры' });
    expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Встреча');
    expect(screen.getByText('01.11–30.11 · Встреча')).toBeInTheDocument();
    expect(screen.queryByText(/Legacy/)).not.toBeInTheDocument();
  });

  it('shows an unknown outcome value as it came', async () => {
    visitsMock.mockResolvedValue([row({ outcome: 'something_new' })]);
    renderPage('/measurements/visits?from=2026-10-01&to=2026-10-31');

    expect(await screen.findByText('something_new')).toBeInTheDocument();
  });

  it('copies the lead id as text', async () => {
    const user = userEvent.setup();
    visitsMock.mockResolvedValue([row()]);
    renderPage('/measurements/visits?from=2026-10-01&to=2026-10-31');

    await user.click(await screen.findByRole('button', { name: 'Копировать' }));

    expect(await navigator.clipboard.readText()).toBe('24681357');
    expect(screen.getByRole('button', { name: 'Скопировано' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /24681357/ })).not.toBeInTheDocument();
  });

  it('says only the first N are shown when the API returned exactly the limit', async () => {
    visitsMock.mockResolvedValue(
      Array.from({ length: MEASUREMENTS_VISITS_LIMIT_DEFAULT }, (_, i) => row({ task_id: i + 1 })),
    );
    renderPage('/measurements/visits?from=2026-01-01&to=2026-10-31');

    expect(
      await screen.findByText('Показаны первые 200 замеров — сузьте период.'),
    ).toBeInTheDocument();
  });

  it('does not say so below the limit', async () => {
    visitsMock.mockResolvedValue(
      Array.from({ length: MEASUREMENTS_VISITS_LIMIT_DEFAULT - 1 }, (_, i) => row({ task_id: i + 1 })),
    );
    renderPage('/measurements/visits?from=2026-01-01&to=2026-10-31');

    await screen.findByRole('table', { name: 'Замеры' });
    expect(screen.queryByText(/Показаны первые/)).not.toBeInTheDocument();
  });

  it('shows the empty state', async () => {
    visitsMock.mockResolvedValue([]);
    renderPage('/measurements/visits?from=2026-10-01&to=2026-10-31');

    expect(await screen.findByText('За период замеров нет')).toBeInTheDocument();
  });

  it('goes back to the metrics with the filters it came from', async () => {
    const user = userEvent.setup();
    visitsMock.mockResolvedValue([row()]);
    renderPage('/measurements/visits?from=2026-10-01&to=2026-10-31', {
      back: '?group_by=week&measurer=Matt+Measurement',
    });

    await user.click(await screen.findByRole('link', { name: '← К метрикам' }));

    expect(screen.getByTestId('location')).toHaveTextContent(
      '/measurements?group_by=week&measurer=Matt+Measurement',
    );
  });

  it('without router state goes back to the metrics defaults', async () => {
    visitsMock.mockResolvedValue([row()]);
    renderPage('/measurements/visits?from=2026-10-01&to=2026-10-31');

    expect(await screen.findByRole('link', { name: '← К метрикам' })).toHaveAttribute(
      'href',
      '/measurements',
    );
  });
});
