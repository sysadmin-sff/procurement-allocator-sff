import { BASE_URL } from '../api/client';
import styles from './LoginPage.module.css';

/** Plain <a> href, not fetch/XHR — the OAuth flow needs a full browser
 * navigation to /auth/login (ADR-0024 §1/§7), an AJAX request can't follow
 * the resulting redirect chain through Google and back. */
export function LoginPage() {
  return (
    <div className={styles.wrap}>
      <div className={styles.card}>
        <h1 className={styles.title}>SCREEN FACTORY · Закупки</h1>
        <p className={styles.description}>
          Войдите через корпоративный аккаунт Google Workspace, чтобы продолжить.
        </p>
        <a className={styles.googleLink} href={`${BASE_URL}/auth/login`}>
          Войти через Google
        </a>
      </div>
    </div>
  );
}
