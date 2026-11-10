import { measurementsApi } from '../../api/measurements';
import styles from '../../components/CrudScreen.module.css';
import { MeasurementsLoadError } from './MeasurementsLoadError';
import { useMeasurementsRequest } from './useMeasurementsRequest';

export function MeasurementVisitsPage() {
  const request = useMeasurementsRequest('visits', () => measurementsApi.visits({}));

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <h1 className={styles.title}>Замеры за период</h1>
        </div>
        <div className={styles.card}>
          {request.status === 'loading' && <div className={styles.loading}>Загрузка…</div>}
          {request.status === 'error' && (
            <MeasurementsLoadError error={request.error} onRetry={request.reload} />
          )}
        </div>
      </div>
    </div>
  );
}
