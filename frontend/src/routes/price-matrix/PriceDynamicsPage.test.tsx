import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PriceDynamicsPage } from './PriceDynamicsPage';
import { pricesApi } from '../../api/prices';
import type { PriceDynamics, PriceDynamicsPoint, PriceDynamicsSeries } from '../../api/types';

vi.mock('../../api/prices', () => ({
  pricesApi: { dynamics: vi.fn() },
}));

const dynamicsMock = vi.mocked(pricesApi.dynamics);

function point(month: string, pct: number | null, compared = 3): PriceDynamicsPoint {
  return { month, avg_change_pct: pct, compared: pct == null ? 0 : compared, up: 1, down: 0 };
}

function supplier(id: string, name: string, values: (number | null)[], compared = 3): PriceDynamicsSeries {
  return {
    supplier_id: id,
    name,
    short_name: null,
    points: values.map((v, i) => point(MONTHS[i], v, compared)),
  };
}

const MONTHS = ['2026-09', '2026-10', '2026-11'];

function fixture(supplierCount = 2): PriceDynamics {
  const suppliers = [
    supplier('ems', 'EMS', [0, 2.5, -1.25], 10),
    supplier('fast', 'Fasteners', [null, 0, 4], 2),
  ];
  for (let i = suppliers.length; i < supplierCount; i += 1) {
    suppliers.push(supplier(`s${i}`, `Supplier ${i}`, [0, 0, 0], 1));
  }
  return {
    as_of: '2026-11-17',
    months: [
      { month: '2026-09', start: '2026-09-01', end: '2026-09-30', is_partial: false },
      { month: '2026-10', start: '2026-10-01', end: '2026-10-31', is_partial: false },
      { month: '2026-11', start: '2026-11-01', end: '2026-11-17', is_partial: true },
    ],
    overall: [point('2026-09', 0), point('2026-10', 1.75), point('2026-11', 0.5)],
    suppliers,
  };
}

function renderPage(url = '/prices/dynamics') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/prices/dynamics" element={<PriceDynamicsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('PriceDynamicsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    dynamicsMock.mockResolvedValue(fixture());
  });

  it('loads the last 12 months by default and shows a table of monthly averages', async () => {
    renderPage();
    const table = await screen.findByRole('table');
    expect(dynamicsMock).toHaveBeenCalledWith(null, null);

    const ems = within(table).getByText('EMS').closest('tr')!;
    expect(within(ems).getByText('+2.50%').className).toMatch(/cellUp/);
    expect(within(ems).getByText('-1.25%').className).toMatch(/cellDown/);
    const fast = within(table).getByText('Fasteners').closest('tr')!;
    expect(within(fast).getByText('—')).toBeInTheDocument();
    expect(within(table).getByText('В среднем по всем')).toBeInTheDocument();
  });

  it('links a month value to the price table filtered to that month', async () => {
    renderPage();
    const link = await screen.findByRole('link', { name: '+2.50%' });
    expect(link).toHaveAttribute('href', '/prices?compare_to=2026-10-01&period_end=2026-10-31&changed=1');
    expect(link).toHaveAttribute('title', expect.stringContaining('Сравнено позиций: 10'));
  });

  it('selecting a year requests that year', async () => {
    renderPage();
    await screen.findByRole('table');
    const year = String(new Date().getFullYear() - 1);
    fireEvent.click(screen.getByRole('button', { name: year }));
    await waitFor(() => expect(dynamicsMock).toHaveBeenLastCalledWith(`${year}-01`, `${year}-12`));
  });

  it('toggles suppliers on the chart and keeps colors of the remaining ones', async () => {
    renderPage();
    await screen.findByRole('table');
    const legend = screen.getByRole('list', { name: 'Легенда' });
    expect(within(legend).getByText('EMS')).toBeInTheDocument();
    expect(within(legend).getByText('Fasteners')).toBeInTheDocument();
    const swatchColor = (name: string) =>
      within(legend).getByText(name).closest('li')!.querySelector('span')!.style.getPropertyValue('--swatch');
    const fastColor = swatchColor('Fasteners');
    expect(fastColor).not.toBe('');

    fireEvent.click(screen.getByLabelText('Показать EMS на графике'));

    expect(within(legend).queryByText('EMS')).not.toBeInTheDocument();
    expect(swatchColor('Fasteners')).toBe(fastColor);
  });

  it('allows at most eight suppliers on the chart', async () => {
    dynamicsMock.mockResolvedValue(fixture(10));
    renderPage();
    await screen.findByRole('table');
    for (const name of ['Supplier 5', 'Supplier 6', 'Supplier 7']) {
      fireEvent.click(screen.getByLabelText(`Показать ${name} на графике`));
    }
    expect(screen.getByLabelText('Показать Supplier 8 на графике')).toBeDisabled();
  });

  it('shows a tooltip with all shown series for the hovered month', async () => {
    renderPage();
    await screen.findByRole('table');
    fireEvent.mouseEnter(screen.getByTestId('chart-hover-2026-10'));
    const tooltip = screen.getByRole('tooltip');
    expect(within(tooltip).getByText('Октябрь 2026')).toBeInTheDocument();
    expect(within(tooltip).getByText('+2.50%')).toBeInTheDocument();
    expect(within(tooltip).getByText('+1.75%')).toBeInTheDocument();
  });
});
