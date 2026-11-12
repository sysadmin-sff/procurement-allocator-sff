import type { MeasurementsMetrics } from '../../api/measurements';
import { Alert } from '../../components/Alert';
import { Button } from '../../components/Button';
import { formatDataAsOf } from './format';
import styles from './Measurements.module.css';

/** «Данные на …» in the module zone, plus the recompute warning (ADR-0053 §3). */
export function DataFreshness({ data, onReload }: { data: MeasurementsMetrics; onReload: () => void }) {
  return (
    <>
      <div className={styles.freshness}>
        {data.data_as_of == null
          ? 'Синхронизация с amoCRM ещё не выполнялась'
          : `Данные на ${formatDataAsOf(data.data_as_of, data.timezone)}`}
      </div>
      {data.outcomes_stale > 0 && (
        <Alert
          variant="warning"
          title="Часть данных пересчитывается"
          action={
            <Button variant="secondary" onClick={onReload}>
              Обновить
            </Button>
          }
        >
          Исходы {data.outcomes_stale} замеров посчитаны по прежней версии правил — числа могут
          измениться после пересчёта.
        </Alert>
      )}
    </>
  );
}
