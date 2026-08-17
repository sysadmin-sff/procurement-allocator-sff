import { ApiError } from '../api/client';
import styles from './ErrorBanner.module.css';

interface ErrorBannerProps {
  error: unknown;
  /** Message shown when the API returned 409 (FK conflict / immutable-record conflict). */
  conflictMessage?: string;
}

export function ErrorBanner({ error, conflictMessage }: ErrorBannerProps) {
  if (!error) return null;

  const message = resolveMessage(error, conflictMessage);

  return (
    <div className={styles.banner} role="alert">
      {message}
    </div>
  );
}

function resolveMessage(error: unknown, conflictMessage?: string): string {
  if (error instanceof ApiError) {
    if (error.status === 409 && conflictMessage) {
      return conflictMessage;
    }
    if (typeof error.detail === 'string') {
      return error.detail;
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'Неизвестная ошибка. Попробуйте ещё раз.';
}
