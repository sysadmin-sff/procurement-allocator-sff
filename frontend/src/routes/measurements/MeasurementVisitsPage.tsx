import { useMemo } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import {
  MEASUREMENTS_VISITS_LIMIT_DEFAULT,
  measurementsApi,
  type MeasurementsVisitsQuery,
} from '../../api/measurements';
import { Alert } from '../../components/Alert';
import { EmptyState } from '../../components/EmptyState';
import crud from '../../components/CrudScreen.module.css';
import { CopyableId } from './CopyableId';
import {
  KIND_LABEL,
  RESULT_SOURCE_LABEL,
  formatDate,
  formatRange,
  measurerLabel,
  outcomeLabel,
} from './format';
import type { VisitsBackState } from './links';
import { MeasurementsLoadError } from './MeasurementsLoadError';
import { useMeasurementsRequest } from './useMeasurementsRequest';
import { readVisitsQuery } from './useMetricsFilters';
import styles from './Measurements.module.css';

/* «Замеры за период» — GET /measurements/metrics/visits with the URL
   parameters as they are. All visits of the range are listed, not only the
   conducted ones: the API has no such filter (docs/known-issues.md). Lead
   ids are text; no amo link — the backend does not expose the amo base URL. */

function describeQuery(query: MeasurementsVisitsQuery): string {
  const parts = [
    query.from != null && query.to != null
      ? formatRange(query.from, query.to)
      : 'период по умолчанию (текущий месяц)',
  ];
  if (query.measurer != null) parts.push(query.measurer);
  if (query.kind != null) parts.push(KIND_LABEL[query.kind]);
  return parts.join(' · ');
}

export function MeasurementVisitsPage() {
  const [params] = useSearchParams();
  const location = useLocation();
  const query = useMemo(() => readVisitsQuery(params), [params]);
  const request = useMeasurementsRequest(JSON.stringify(query), () =>
    measurementsApi.visits(query),
  );
  const back = (location.state as VisitsBackState | null)?.back ?? '';

  return (
    <div className={crud.page}>
      <div className={`${crud.inner} ${styles.wide}`}>
        <Link to={`/measurements${back}`} className={crud.backLink}>
          ← К метрикам
        </Link>
        <div className={crud.header}>
          <h1 className={crud.title}>Замеры за период</h1>
        </div>

        <div className={crud.stack}>
          <div className={styles.filterSummary}>{describeQuery(query)}</div>

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

          {request.status === 'ready' && request.data.length === 0 && (
            <div className={crud.card}>
              <EmptyState title="За период замеров нет" description="Выберите другой период." />
            </div>
          )}

          {request.status === 'ready' && request.data.length > 0 && (
            <>
              {request.data.length === MEASUREMENTS_VISITS_LIMIT_DEFAULT && (
                <Alert variant="info" compact>
                  Показаны первые {MEASUREMENTS_VISITS_LIMIT_DEFAULT} замеров — сузьте период.
                </Alert>
              )}
              <div className={`${styles.panel} ${styles.tableScroll}`}>
                <table className={styles.table} aria-label="Замеры">
                  <thead>
                    <tr>
                      <th>Дата</th>
                      <th>Замерщик</th>
                      <th>Тип</th>
                      <th>Источник результата</th>
                      <th>Исход</th>
                      <th>Выполнен</th>
                      <th>Дубль</th>
                      <th>ID сделки</th>
                    </tr>
                  </thead>
                  <tbody>
                    {request.data.map((visit) => (
                      <tr key={visit.task_id}>
                        <td>{formatDate(visit.local_date)}</td>
                        <td>{measurerLabel(visit.measurer_key)}</td>
                        <td>{KIND_LABEL[visit.kind] ?? visit.kind}</td>
                        <td>{RESULT_SOURCE_LABEL[visit.result_source] ?? visit.result_source}</td>
                        <td>{outcomeLabel(visit.outcome)}</td>
                        <td>{visit.is_completed ? 'Да' : 'Нет'}</td>
                        <td>{visit.is_duplicate ? 'Дубль' : '—'}</td>
                        <td>
                          <CopyableId value={visit.lead_id} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
