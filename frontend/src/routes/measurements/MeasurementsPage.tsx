import { measurementsApi } from '../../api/measurements';
import styles from '../../components/CrudScreen.module.css';
import { MeasurementsLoadError } from './MeasurementsLoadError';
import { useMeasurementsRequest } from './useMeasurementsRequest';

export function MeasurementsPage() {
  const request = useMeasurementsRequest('metrics', () => measurementsApi.metrics({}));

  return (
    <div className={styles.page}>
      <div className={styles.inner}>
        <div className={styles.header}>
          <h1 className={styles.title}>Замеры</h1>
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
