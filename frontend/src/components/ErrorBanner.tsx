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
  // A raw fetch() rejection never reached the backend at all (offline,
  // backend down, CORS) — the browser's own TypeError message ("Failed to
  // fetch" in Chrome, "NetworkError when attempting to fetch resource." in
  // Firefox) is not something an employee can act on, unlike ApiError's
  // server-authored detail text.
  if (error instanceof TypeError) {
    return 'Не удалось связаться с сервером. Проверьте соединение и попробуйте ещё раз.';
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'Неизвестная ошибка. Попробуйте ещё раз.';
}
