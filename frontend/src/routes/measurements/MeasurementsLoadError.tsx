import { ApiError } from '../../api/client';
import { Button } from '../../components/Button';
import { EmptyState } from '../../components/EmptyState';
import { ErrorBanner } from '../../components/ErrorBanner';
import styles from '../../components/CrudScreen.module.css';

/** 403 — no admin role and no grant (ADR-0051 §2); 404 — module switched off
 * (MEASUREMENTS_ENABLED=false, the routes do not exist). Neither is retried. */
export function MeasurementsLoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  if (error instanceof ApiError && error.status === 403) {
    return (
      <EmptyState
        title="Нет доступа к разделу «Замеры»"
        description="Доступ выдаёт администратор."
      />
    );
  }
  if (error instanceof ApiError && error.status === 404) {
    return (
      <EmptyState
        title="Раздел «Замеры» выключен"
        description="Модуль не включён на этом сервере."
      />
    );
  }
  return (
    <div className={`${styles.cardPadded} ${styles.stack}`}>
      <ErrorBanner error={error} />
      <div>
        <Button variant="secondary" onClick={onRetry}>
          Повторить
        </Button>
      </div>
    </div>
  );
}
