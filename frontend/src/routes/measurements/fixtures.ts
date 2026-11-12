import type {
  MeasurementsMeasurerMetrics,
  MeasurementsMetrics,
  MeasurementsMetricsBlock,
  MeasurementsPeriod,
} from '../../api/measurements';

/* Test data only. Values echo ADR-0053 «Критерии приёмки» §3 (October 2026 on
   the dev DB). M3 is deliberately not additive (company 15 ≠ 9 + 7): the
   company's visit days are distinct dates across measurers, so any client
   summation shows up as a wrong number. */

export const MATT = 'Matt Measurement';
export const NAZAR = 'Nazar';

export function block(overrides: Partial<MeasurementsMetricsBlock> = {}): MeasurementsMetricsBlock {
  return {
    conducted: { total: 0, primary: 0, additional: 0, legacy: 0 },
    planned: { upcoming: 0, overdue: 0 },
    visit_days: 0,
    per_visit_day: null,
    per_week_avg: null,
    data_quality: {
      without_site_visit_result: { completed: 0, not_completed: 0 },
      no_outcome: 0,
      duplicates: 0,
    },
    ...overrides,
  };
}

export function measurer(
  key: string | null,
  overrides: Partial<MeasurementsMetricsBlock> = {},
): MeasurementsMeasurerMetrics {
  return { measurer_key: key, ...block(overrides) };
}

const companyTotal = block({
  conducted: { total: 64, primary: 41, additional: 6, legacy: 17 },
  planned: { upcoming: 5, overdue: 2 },
  visit_days: 15,
  per_visit_day: '4.27',
  per_week_avg: '14.45',
  data_quality: {
    without_site_visit_result: { completed: 3, not_completed: 1 },
    no_outcome: 7,
    duplicates: 1,
  },
});

const nazarTotal = measurer(NAZAR, {
  conducted: { total: 34, primary: 22, additional: 3, legacy: 9 },
  planned: { upcoming: 3, overdue: 1 },
  visit_days: 9,
  per_visit_day: '3.78',
  per_week_avg: '7.68',
  data_quality: {
    without_site_visit_result: { completed: 2, not_completed: 0 },
    no_outcome: 4,
    duplicates: 1,
  },
});

const mattTotal = measurer(MATT, {
  conducted: { total: 30, primary: 19, additional: 3, legacy: 8 },
  planned: { upcoming: 2, overdue: 1 },
  visit_days: 7,
  per_visit_day: '4.29',
  per_week_avg: '6.77',
  data_quality: {
    without_site_visit_result: { completed: 1, not_completed: 1 },
    no_outcome: 3,
    duplicates: 0,
  },
});

export function monthMetrics(): MeasurementsMetrics {
  return {
    timezone: 'America/New_York',
    requested: { from: '2026-10-01', to: '2026-10-31' },
    from: '2026-10-01',
    to: '2026-10-31',
    group_by: 'month',
    data_as_of: '2026-11-11T14:05:00Z',
    outcomes_stale: 0,
    periods: [
      {
        period_start: '2026-10-01',
        period_end: '2026-10-31',
        days: 31,
        is_partial: false,
        company: companyTotal,
        measurers: [nazarTotal, mattTotal],
      },
    ],
    total: { days: 31, is_partial: false, company: companyTotal, measurers: [nazarTotal, mattTotal] },
  };
}

function week(
  start: string,
  end: string,
  total: number,
  nazar: number,
  matt: number,
  extra: Partial<MeasurementsPeriod> = {},
): MeasurementsPeriod {
  return {
    period_start: start,
    period_end: end,
    days: 7,
    is_partial: false,
    company: block({
      conducted: { total, primary: total, additional: 0, legacy: 0 },
      visit_days: 4,
      per_visit_day: '3.10',
      per_week_avg: `${total}.00`,
    }),
    measurers: [
      measurer(NAZAR, { conducted: { total: nazar, primary: nazar, additional: 0, legacy: 0 } }),
      measurer(MATT, { conducted: { total: matt, primary: matt, additional: 0, legacy: 0 } }),
    ],
    ...extra,
  };
}

/** October by weeks: aligned to 28.09–01.11, company M1 15, 11, 8, 21, 18. */
export function weekMetrics(): MeasurementsMetrics {
  return {
    ...monthMetrics(),
    from: '2026-09-28',
    to: '2026-11-01',
    group_by: 'week',
    periods: [
      week('2026-09-28', '2026-10-04', 15, 8, 7),
      week('2026-10-05', '2026-10-11', 11, 6, 5),
      week('2026-10-12', '2026-10-18', 8, 4, 4),
      week('2026-10-19', '2026-10-25', 21, 11, 10),
      week('2026-10-26', '2026-11-01', 18, 9, 9, { is_partial: true }),
    ],
  };
}

/** A range with no visits at all: the API returns no measurers. */
export function emptyMetrics(): MeasurementsMetrics {
  const empty = monthMetrics();
  return {
    ...empty,
    periods: empty.periods.map((p) => ({ ...p, company: block(), measurers: [] })),
    total: { ...empty.total, company: block(), measurers: [] },
  };
}
