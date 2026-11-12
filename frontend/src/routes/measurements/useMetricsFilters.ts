import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type {
  MeasurementsGroupBy,
  MeasurementsMetricsQuery,
  MeasurementsVisitKind,
  MeasurementsVisitsQuery,
} from '../../api/measurements';

/* Filters live in the URL under the API's own parameter names. An absent
   parameter is neither written nor sent, so the API picks its defaults
   (current NY month, group_by=month). */

function text(params: URLSearchParams, key: string): string | undefined {
  const value = params.get(key);
  return value == null || value === '' ? undefined : value;
}

function oneOf<T extends string>(value: string | undefined, allowed: readonly T[]): T | undefined {
  return allowed.find((item) => item === value);
}

const GROUP_BY: readonly MeasurementsGroupBy[] = ['week', 'month'];
const KINDS: readonly MeasurementsVisitKind[] = ['primary', 'additional', 'legacy'];

function compact<T extends object>(value: T): T {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => item !== undefined),
  ) as T;
}

export function readMetricsQuery(params: URLSearchParams): MeasurementsMetricsQuery {
  return compact({
    from: text(params, 'from'),
    to: text(params, 'to'),
    group_by: oneOf(text(params, 'group_by'), GROUP_BY),
    measurer: text(params, 'measurer'),
  });
}

export function readVisitsQuery(params: URLSearchParams): MeasurementsVisitsQuery {
  return compact({
    from: text(params, 'from'),
    to: text(params, 'to'),
    measurer: text(params, 'measurer'),
    kind: oneOf(text(params, 'kind'), KINDS),
  });
}

export function useMetricsFilters() {
  const [params, setParams] = useSearchParams();
  const query = useMemo(() => readMetricsQuery(params), [params]);

  const update = useCallback(
    (patch: Partial<Record<keyof MeasurementsMetricsQuery, string | undefined>>) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(patch)) {
            if (value == null || value === '') next.delete(key);
            else next.set(key, value);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  return { query, update };
}
