import { useEffect, useState } from 'react';
import { ApiError } from '../../api/client';
import {
  measurementsApi,
  type MeasurementsMetrics,
  type MeasurementsMetricsQuery,
} from '../../api/measurements';
import { EmptyState } from '../../components/EmptyState';
import crud from '../../components/CrudScreen.module.css';
import { DataFreshness } from './DataFreshness';
import { DataQualitySection } from './DataQualitySection';
import { DynamicsChart } from './DynamicsChart';
import { companyEntity, measurerEntities } from './entities';
import { ALIGNMENT_LABEL, formatRange } from './format';
import { MeasurementsLoadError } from './MeasurementsLoadError';
import { MetricsFilters } from './MetricsFilters';
import { PeriodsTable } from './PeriodsTable';
import { PlannedSection } from './PlannedSection';
import { SummarySection } from './SummarySection';
import { useMeasurementsRequest } from './useMeasurementsRequest';
import { useMetricsFilters } from './useMetricsFilters';
import styles from './Measurements.module.css';

/* Screen «Замеры» (ADR-0051, ADR-0053 §5). Every number is a field of the
   GET /measurements/metrics response — nothing is summed or derived here. */

/** No visits in the range: without a measurer filter the API lists no
 * measurer groups; with one, the selected group has nothing to show. */
function isEmpty(data: MeasurementsMetrics, query: MeasurementsMetricsQuery): boolean {
  if (query.measurer == null) return data.total.measurers.length === 0;
  const company = data.total.company;
  return (
    company.conducted.total === 0 && company.planned.upcoming === 0 && company.planned.overdue === 0
  );
}

function isAccessError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 403 || error.status === 404);
}

export function MeasurementsPage() {
  const { query, update } = useMetricsFilters();
  const key = JSON.stringify(query);
  const request = useMeasurementsRequest(key, () => measurementsApi.metrics(query));

  // Measurer keys come from the last response without a measurer filter: a
  // filtered response lists only the selected measurer.
  const [knownMeasurers, setKnownMeasurers] = useState<string[]>([]);
  useEffect(() => {
    if (request.status !== 'ready' || request.dataKey !== key || query.measurer != null) return;
    setKnownMeasurers(
      request.data.total.measurers
        .map((m) => m.measurer_key)
        .filter((k): k is string => k != null),
    );
  }, [request.status, request.data, request.dataKey, key, query.measurer]);

  const measurerOptions =
    query.measurer != null && !knownMeasurers.includes(query.measurer)
      ? [...knownMeasurers, query.measurer]
      : knownMeasurers;

  const data = request.data;
  const showFilters = !(request.status === 'error' && isAccessError(request.error));

  return (
    <div className={crud.page}>
      <div className={`${crud.inner} ${styles.wide}`}>
        <div className={crud.header}>
          <h1 className={crud.title}>Замеры</h1>
        </div>

        <div className={crud.stack}>
          {showFilters && (
            <div className={styles.toolbar}>
              <MetricsFilters
                query={query}
                requested={data?.requested}
                groupBy={query.group_by ?? data?.group_by ?? 'month'}
                measurerOptions={measurerOptions}
                onChange={update}
              />
              {data != null &&
                (data.from !== data.requested.from || data.to !== data.requested.to) && (
                  <div className={styles.rangeNotice}>
                    Показано {formatRange(data.from, data.to)} ({ALIGNMENT_LABEL[data.group_by]})
                  </div>
                )}
            </div>
          )}

          {request.status === 'loading' && (
            <div className={crud.card}>
              <div className={crud.loading}>Загрузка…</div>
            </div>
          )}

          {request.status === 'error' && (
            <div className={crud.card}>
              <MeasurementsLoadError error={request.error} onRetry={request.reload} />
            </div>
          )}

          {request.status === 'ready' && data != null && (
            <>
              <DataFreshness data={data} onReload={request.reload} />
              {isEmpty(data, query) ? (
                <div className={crud.card}>
                  <EmptyState
                    title="За период замеров нет"
                    description="Выберите другой диапазон или замерщика."
                  />
                </div>
              ) : (
                <MetricsSections data={data} query={query} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function MetricsSections({
  data,
  query,
}: {
  data: MeasurementsMetrics;
  query: MeasurementsMetricsQuery;
}) {
  const measurers = measurerEntities(data.total.measurers);
  const entities = [companyEntity(query.measurer), ...measurers];
  return (
    <>
      <SummarySection data={data} entities={entities} />
      <DynamicsChart data={data} measurers={measurers} />
      <PeriodsTable data={data} entities={entities} />
      <div className={styles.twoColumns}>
        <PlannedSection data={data} entities={entities} />
        <DataQualitySection data={data} entities={entities} />
      </div>
    </>
  );
}
