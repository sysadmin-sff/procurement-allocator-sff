import { http } from './client';

/* Types mirror backend/app/measurements/router.py (ADR-0051 §2, ADR-0053 §5).
   Ratios (per_visit_day, per_week_avg) arrive as decimal strings computed on
   the backend — the frontend displays them as-is and never parses them. */

export type MeasurementsGroupBy = 'week' | 'month';
export type MeasurementsVisitKind = 'primary' | 'additional' | 'legacy';

export interface MeasurementsAccess {
  access: boolean;
}

export interface MeasurementsStream {
  stream: string;
  watermark_at: string | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_status: string | null;
  last_http_status: number | null;
  consecutive_failures: number;
  heartbeat_at: string | null;
  counters: Record<string, number>;
}

export interface MeasurementsStatus {
  last_sync_at: string | null;
  streams: MeasurementsStream[];
  counts: { leads: number; visits: number; events: number };
  outcomes_stale: number;
}

export interface MeasurementsMetricsBlock {
  conducted: { total: number; primary: number; additional: number; legacy: number };
  planned: { upcoming: number; overdue: number };
  visit_days: number;
  /** Decimal string, 2 places; null when there are no visit days. */
  per_visit_day: string | null;
  /** Decimal string, 2 places; null for a period with no elapsed days. */
  per_week_avg: string | null;
  data_quality: {
    without_site_visit_result: { completed: number; not_completed: number };
    no_outcome: number;
    duplicates: number;
  };
}

export interface MeasurementsMeasurerMetrics extends MeasurementsMetricsBlock {
  /** null — visits whose responsible user is not in the measurer map. */
  measurer_key: string | null;
}

export interface MeasurementsPeriod {
  period_start: string;
  period_end: string;
  days: number;
  is_partial: boolean;
  company: MeasurementsMetricsBlock;
  measurers: MeasurementsMeasurerMetrics[];
}

export interface MeasurementsMetrics {
  timezone: string;
  requested: { from: string; to: string };
  /** Aligned to whole weeks/months. */
  from: string;
  to: string;
  group_by: MeasurementsGroupBy;
  /** UTC with Z, or null before the first successful sync. */
  data_as_of: string | null;
  outcomes_stale: number;
  periods: MeasurementsPeriod[];
  total: {
    days: number;
    is_partial: boolean;
    company: MeasurementsMetricsBlock;
    measurers: MeasurementsMeasurerMetrics[];
  };
}

export interface MeasurementsVisitRow {
  task_id: number;
  lead_id: number;
  local_date: string;
  measurer_key: string | null;
  kind: MeasurementsVisitKind;
  result_source: string;
  outcome: string | null;
  is_completed: boolean;
  is_duplicate: boolean;
}

export interface MeasurementsMetricsQuery {
  from?: string;
  to?: string;
  group_by?: MeasurementsGroupBy;
  measurer?: string;
}

export interface MeasurementsVisitsQuery {
  from?: string;
  to?: string;
  measurer?: string;
  kind?: MeasurementsVisitKind;
}

/** Mirror of backend VISITS_LIMIT_DEFAULT (app/measurements/metrics.py). The
 * API does not report truncation, so a response of exactly this many rows is
 * shown as "first N" (docs/known-issues.md). */
export const MEASUREMENTS_VISITS_LIMIT_DEFAULT = 200;

/** Omits empty values so the API applies its own defaults. */
export function measurementsQueryString(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === 'string' && value !== '') search.set(key, value);
  }
  const text = search.toString();
  return text === '' ? '' : `?${text}`;
}

export const measurementsApi = {
  access: () => http.get<MeasurementsAccess>('/measurements/access'),
  status: () => http.get<MeasurementsStatus>('/measurements/status'),
  metrics: (query: MeasurementsMetricsQuery) =>
    http.get<MeasurementsMetrics>(`/measurements/metrics${measurementsQueryString(query)}`),
  visits: (query: MeasurementsVisitsQuery) =>
    http.get<MeasurementsVisitRow[]>(
      `/measurements/metrics/visits${measurementsQueryString(query)}`,
    ),
};
