import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { measurementsApi } from '../../api/measurements';
import { MeasurementsPage } from './MeasurementsPage';
import { MATT, NAZAR, block, emptyMetrics, measurer, monthMetrics, weekMetrics } from './fixtures';

vi.mock('../../api/measurements', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/measurements')>()),
  measurementsApi: { access: vi.fn(), metrics: vi.fn(), visits: vi.fn(), status: vi.fn() },
}));

const metricsMock = vi.mocked(measurementsApi.metrics);

function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="location">
      {location.pathname}
      {location.search}
    </div>
  );
}

function currentSearch() {
  const text = screen.getByTestId('location').textContent ?? '';
  return new URLSearchParams(text.split('?')[1] ?? '');
}

function renderPage(path = '/measurements') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/measurements" element={<MeasurementsPage />} />
        <Route path="/measurements/visits" element={<div>Детализация</div>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}

// The browser zone must not show through: pin one far from New York.
beforeAll(() => {
  vi.stubEnv('TZ', 'Asia/Tokyo');
});
afterAll(() => {
  vi.unstubAllEnvs();
});

describe('MeasurementsPage — сводка', () => {
  beforeEach(() => {
    metricsMock.mockReset();
  });

  it('requests the API defaults when the URL has no filters', async () => {
    metricsMock.mockResolvedValue(monthMetrics());
    renderPage();

    await screen.findByRole('article', { name: 'Компания' });
    expect(metricsMock).toHaveBeenCalledWith({});
  });

  it('renders the company card exactly from total.company, not from measurers', async () => {
    metricsMock.mockResolvedValue(monthMetrics());
    renderPage();

    const company = await screen.findByRole('article', { name: 'Компания' });
    expect(within(company).getByTestId('conducted-total')).toHaveTextContent('64');
    expect(within(company).getByTestId('conducted-primary')).toHaveTextContent('41');
    expect(within(company).getByTestId('conducted-additional')).toHaveTextContent('6');
    expect(within(company).getByTestId('conducted-legacy')).toHaveTextContent('17');
    // M3 is not additive: 15, not 9 + 7.
    expect(within(company).getByTestId('visit-days')).toHaveTextContent(/^15$/);
    expect(within(company).getByTestId('per-visit-day')).toHaveTextContent(/^4\.27$/);
    expect(within(company).getByTestId('per-week-avg')).toHaveTextContent(/^14\.45$/);
  });

  it('renders a card per measurer from total.measurers', async () => {
    metricsMock.mockResolvedValue(monthMetrics());
    renderPage();

    const nazar = await screen.findByRole('article', { name: NAZAR });
    expect(within(nazar).getByTestId('conducted-total')).toHaveTextContent('34');
    expect(within(nazar).getByTestId('visit-days')).toHaveTextContent(/^9$/);
    expect(within(nazar).getByTestId('per-visit-day')).toHaveTextContent(/^3\.78$/);
    const matt = screen.getByRole('article', { name: MATT });
    expect(within(matt).getByTestId('per-week-avg')).toHaveTextContent(/^6\.77$/);
  });

  it('shows decimal strings as they came, trailing zeros included', async () => {
    const data = monthMetrics();
    data.total.company = { ...data.total.company, per_visit_day: '3.10', per_week_avg: '2.50' };
    metricsMock.mockResolvedValue(data);
    renderPage();

    const company = await screen.findByRole('article', { name: 'Компания' });
    expect(within(company).getByTestId('per-visit-day')).toHaveTextContent(/^3\.10$/);
    expect(within(company).getByTestId('per-week-avg')).toHaveTextContent(/^2\.50$/);
  });

  it('shows «—» for null ratios (no visit days, future period)', async () => {
    const data = monthMetrics();
    data.total.company = block();
    metricsMock.mockResolvedValue(data);
    renderPage();

    const company = await screen.findByRole('article', { name: 'Компания' });
    expect(within(company).getByTestId('per-visit-day')).toHaveTextContent(/^—$/);
    expect(within(company).getByTestId('per-week-avg')).toHaveTextContent(/^—$/);
  });

  it('labels the null measurer group and gives it no detail link', async () => {
    const data = monthMetrics();
    data.total.measurers = [
      ...data.total.measurers,
      measurer(null, { conducted: { total: 2, primary: 2, additional: 0, legacy: 0 } }),
    ];
    metricsMock.mockResolvedValue(data);
    renderPage();

    const unassigned = await screen.findByRole('article', { name: 'Без замерщика' });
    expect(within(unassigned).getByTestId('conducted-total')).toHaveTextContent('2');
    expect(within(unassigned).queryByRole('link')).not.toBeInTheDocument();
  });
});

describe('MeasurementsPage — фильтры в URL', () => {
  beforeEach(() => {
    metricsMock.mockReset();
  });

  it('restores filters from the URL, including a measurer key with a space', async () => {
    metricsMock.mockResolvedValue({
      ...weekMetrics(),
      requested: { from: '2026-10-01', to: '2026-10-31' },
    });
    renderPage('/measurements?from=2026-10-01&to=2026-10-31&group_by=week&measurer=Matt%20Measurement');

    await screen.findByRole('article', { name: 'Компания' });
    expect(metricsMock).toHaveBeenCalledWith({
      from: '2026-10-01',
      to: '2026-10-31',
      group_by: 'week',
      measurer: MATT,
    });
    expect(screen.getByLabelText('С')).toHaveValue('2026-10-01');
    expect(screen.getByLabelText('По')).toHaveValue('2026-10-31');
    expect(screen.getByRole('button', { name: 'Неделя' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Замерщик')).toHaveValue(MATT);
  });

  it('writes the measurer with a space to the URL and reads it back', async () => {
    const user = userEvent.setup();
    metricsMock.mockResolvedValue(monthMetrics());
    renderPage();

    await screen.findByRole('option', { name: MATT });
    await user.selectOptions(screen.getByLabelText('Замерщик'), MATT);

    await waitFor(() => expect(currentSearch().get('measurer')).toBe(MATT));
    expect(screen.getByTestId('location').textContent).not.toContain(' ');
    await waitFor(() => expect(metricsMock).toHaveBeenLastCalledWith({ measurer: MATT }));
  });

  it('keeps the measurer list from the last unfiltered response', async () => {
    const user = userEvent.setup();
    metricsMock.mockResolvedValueOnce(monthMetrics());
    const filtered = monthMetrics();
    filtered.total.measurers = [filtered.total.measurers[1]];
    metricsMock.mockResolvedValueOnce(filtered);
    renderPage();

    await screen.findByRole('option', { name: MATT });
    await user.selectOptions(screen.getByLabelText('Замерщик'), MATT);
    await waitFor(() => expect(metricsMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('article', { name: NAZAR })).not.toBeInTheDocument());

    const options = within(screen.getByLabelText('Замерщик')).getAllByRole('option');
    expect(options.map((o) => o.textContent)).toEqual(['Все замерщики', NAZAR, MATT]);
  });

  it('switching grouping makes a new request with group_by and writes it to the URL', async () => {
    const user = userEvent.setup();
    metricsMock.mockResolvedValueOnce(monthMetrics()).mockResolvedValueOnce(weekMetrics());
    renderPage();

    await screen.findByRole('article', { name: 'Компания' });
    await user.click(screen.getByRole('button', { name: 'Неделя' }));

    await waitFor(() => expect(metricsMock).toHaveBeenLastCalledWith({ group_by: 'week' }));
    expect(currentSearch().get('group_by')).toBe('week');
  });

  it('applies dates with «Показать», not on every keystroke', async () => {
    const user = userEvent.setup();
    metricsMock.mockResolvedValue(monthMetrics());
    renderPage();

    await screen.findByRole('article', { name: 'Компания' });
    // jsdom does not type into <input type="date"> key by key.
    fireEvent.change(screen.getByLabelText('С'), { target: { value: '2026-09-01' } });
    expect(metricsMock).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Показать' }));

    await waitFor(() =>
      expect(metricsMock).toHaveBeenLastCalledWith({ from: '2026-09-01', to: '2026-10-31' }),
    );
    expect(currentSearch().get('from')).toBe('2026-09-01');
    expect(currentSearch().get('to')).toBe('2026-10-31');
  });

  it('shows the aligned range when it differs from the requested one', async () => {
    metricsMock.mockResolvedValue(weekMetrics());
    renderPage('/measurements?group_by=week');

    expect(await screen.findByText('Показано 28.09–01.11 (целые недели)')).toBeInTheDocument();
  });

  it('says nothing about alignment when the range was not changed', async () => {
    metricsMock.mockResolvedValue(monthMetrics());
    renderPage();

    await screen.findByRole('article', { name: 'Компания' });
    expect(screen.queryByText(/^Показано/)).not.toBeInTheDocument();
  });
});

describe('MeasurementsPage — динамика и таблица', () => {
  beforeEach(() => {
    metricsMock.mockReset();
  });

  it('draws one bar per period labelled with the company value', async () => {
    metricsMock.mockResolvedValue(weekMetrics());
    renderPage('/measurements?group_by=week');

    const chart = await screen.findByRole('list', { name: 'Динамика проведённых замеров' });
    const bars = within(chart).getAllByRole('listitem');
    expect(bars.map((b) => b.getAttribute('aria-label'))).toEqual([
      '28.09–04.10: 15',
      '05.10–11.10: 11',
      '12.10–18.10: 8',
      '19.10–25.10: 21',
      '26.10–01.11: 18 (неполный период)',
    ]);
  });

  it('splits a bar into measurer segments from the API values', async () => {
    metricsMock.mockResolvedValue(weekMetrics());
    renderPage('/measurements?group_by=week');

    const chart = await screen.findByRole('list', { name: 'Динамика проведённых замеров' });
    const first = within(chart).getAllByRole('listitem')[0];
    expect(within(first).getByTitle(`${NAZAR}: 8`)).toBeInTheDocument();
    expect(within(first).getByTitle(`${MATT}: 7`)).toBeInTheDocument();
  });

  it('marks only the partial period in the chart and in the table', async () => {
    metricsMock.mockResolvedValue(weekMetrics());
    renderPage('/measurements?group_by=week');

    const chart = await screen.findByRole('list', { name: 'Динамика проведённых замеров' });
    const bars = within(chart).getAllByRole('listitem');
    expect(bars.map((b) => b.dataset.partial)).toEqual(['false', 'false', 'false', 'false', 'true']);

    const table = screen.getByRole('table', { name: 'По периодам' });
    const rows = within(table).getAllByRole('row').filter((r) => r.dataset.period != null);
    expect(rows.map((r) => r.dataset.partial)).toEqual(['false', 'false', 'false', 'false', 'true']);
    expect(within(rows[4]).getByText('неполный')).toBeInTheDocument();
    expect(within(rows[0]).queryByText('неполный')).not.toBeInTheDocument();
  });

  it('table cells come from each period and the total row from total', async () => {
    metricsMock.mockResolvedValue(weekMetrics());
    renderPage('/measurements?group_by=week');

    const table = await screen.findByRole('table', { name: 'По периодам' });
    const first = within(table).getByRole('row', { name: /28\.09–04\.10/ });
    expect(within(first).getByTestId('company-m1')).toHaveTextContent('15');
    expect(within(first).getByTestId('company-m4')).toHaveTextContent(/^3\.10$/);
    expect(within(first).getByTestId(`${NAZAR}-m1`)).toHaveTextContent('8');

    const totalRow = within(table).getByRole('row', { name: /Итого/ });
    expect(within(totalRow).getByTestId('company-m1')).toHaveTextContent('64');
    expect(within(totalRow).getByTestId('company-m3')).toHaveTextContent(/^15$/);
    expect(within(totalRow).getByTestId('company-m5')).toHaveTextContent(/^14\.45$/);
  });

  it('month periods are labelled with the month name', async () => {
    metricsMock.mockResolvedValue(monthMetrics());
    renderPage();

    const table = await screen.findByRole('table', { name: 'По периодам' });
    expect(within(table).getByRole('row', { name: /Октябрь 2026/ })).toBeInTheDocument();
  });
});

describe('MeasurementsPage — запланированные, качество, служебная строка', () => {
  beforeEach(() => {
    metricsMock.mockReset();
  });

  it('planned visits come from total for the company and each measurer', async () => {
    metricsMock.mockResolvedValue(monthMetrics());
    renderPage();

    const table = await screen.findByRole('table', { name: 'Запланированные' });
    const company = within(table).getByRole('row', { name: /Компания/ });
    expect(within(company).getByTestId('upcoming')).toHaveTextContent('5');
    expect(within(company).getByTestId('overdue')).toHaveTextContent('2');
    const matt = within(table).getByRole('row', { name: new RegExp(MATT) });
    expect(within(matt).getByTestId('overdue')).toHaveTextContent('1');
  });

  it('data quality numbers come from total and are not links', async () => {
    metricsMock.mockResolvedValue(monthMetrics());
    renderPage();

    const table = await screen.findByRole('table', { name: 'Качество данных' });
    const company = within(table).getByRole('row', { name: /Компания/ });
    expect(within(company).getByTestId('without-result-completed')).toHaveTextContent('3');
    expect(within(company).getByTestId('without-result-not-completed')).toHaveTextContent('1');
    expect(within(company).getByTestId('no-outcome')).toHaveTextContent('7');
    expect(within(company).getByTestId('duplicates')).toHaveTextContent('1');
    expect(within(table).queryByRole('link')).not.toBeInTheDocument();
  });

  it('shows data_as_of in New York time with the zone name', async () => {
    metricsMock.mockResolvedValue(monthMetrics());
    renderPage();

    // 14:05 UTC on 11.11 is 09:05 EST (and 23:05 in Tokyo).
    expect(await screen.findByText('Данные на 11.11.2026, 09:05 (America/New_York)')).toBeInTheDocument();
  });

  it('says when there is no successful sync yet', async () => {
    metricsMock.mockResolvedValue({ ...monthMetrics(), data_as_of: null });
    renderPage();

    expect(await screen.findByText('Синхронизация с amoCRM ещё не выполнялась')).toBeInTheDocument();
  });

  it('warns when outcomes are being recomputed, and not otherwise', async () => {
    metricsMock.mockResolvedValueOnce({ ...monthMetrics(), outcomes_stale: 12 });
    const first = renderPage();

    expect(await screen.findByText('Часть данных пересчитывается')).toBeInTheDocument();
    first.unmount();

    metricsMock.mockResolvedValueOnce(monthMetrics());
    renderPage();
    await screen.findByRole('article', { name: 'Компания' });
    expect(screen.queryByText('Часть данных пересчитывается')).not.toBeInTheDocument();
  });
});

describe('MeasurementsPage — состояния', () => {
  beforeEach(() => {
    metricsMock.mockReset();
  });

  it('shows loading first', async () => {
    metricsMock.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText('Загрузка…')).toBeInTheDocument();
  });

  it('shows the empty state for a range without visits', async () => {
    metricsMock.mockResolvedValue(emptyMetrics());
    renderPage();

    expect(await screen.findByText('За период замеров нет')).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'По периодам' })).not.toBeInTheDocument();
    // Filters stay so the range can be changed.
    expect(screen.getByLabelText('С')).toBeInTheDocument();
  });

  it('shows the empty state for a measurer with nothing in the range', async () => {
    const data = emptyMetrics();
    data.total.measurers = [measurer(MATT)];
    metricsMock.mockResolvedValue(data);
    renderPage('/measurements?measurer=Matt%20Measurement');

    expect(await screen.findByText('За период замеров нет')).toBeInTheDocument();
  });

  it('an invalid range shows the API message and retries on demand', async () => {
    const user = userEvent.setup();
    const { ApiError } = await import('../../api/client');
    metricsMock
      .mockRejectedValueOnce(new ApiError(422, { detail: 'The range is longer than 366 days' }))
      .mockResolvedValueOnce(monthMetrics());
    renderPage('/measurements?from=2024-01-01&to=2026-10-31');

    expect(await screen.findByText('The range is longer than 366 days')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('article', { name: 'Компания' })).toBeInTheDocument();
  });
});
