import { BASE_URL } from '../api/client';
import styles from './LoginPage.module.css';

const SYSADMIN_EMAIL = 'sysadmin@screen-factory-florida.com';
const SYSADMIN_TELEGRAM = 'sa1to21';

/** Plain <a> href, not fetch/XHR — the OAuth flow needs a full browser
 * navigation to /auth/login (ADR-0024 §1/§7), an AJAX request can't follow
 * the resulting redirect chain through Google and back. */
export function LoginPage() {
  return (
    <div className={styles.wrap}>
      <div className={styles.leftPanel}>
        <div className={styles.leftPanelDecoration} />
        <div className={styles.leftPanelDecorationSmall} />

        <div className={styles.leftPanelBody}>
          <div className={styles.eyebrow}>Внутренний инструмент</div>
          <h1 className={styles.leftPanelTitle}>Закупки и расчёт материалов</h1>
          <p className={styles.leftPanelDescription}>
            Импорт прайс-листов, расчёт закупки по проектам и разложение спецификации по
            поставщикам — в одном рабочем месте.
          </p>
        </div>

        <ul className={styles.checklist}>
          <li className={styles.checklistItem}>
            <span className={styles.checklistIcon}>✓</span>
            Доступ по корпоративному аккаунту Google Workspace
          </li>
          <li className={styles.checklistItem}>
            <span className={styles.checklistIcon}>✓</span>
            Роли и права выдаёт администратор
          </li>
        </ul>
      </div>

      <div className={styles.rightPanel}>
        <div className={styles.rightPanelLogoWrap}>
          <img
            src="/logo-horizontal.svg"
            alt="Screen Factory Florida"
            className={styles.rightPanelLogo}
          />
        </div>

        <div className={styles.rightPanelInner}>
          <h2 className={styles.title}>Вход в систему</h2>
          <p className={styles.description}>
            Используйте корпоративный аккаунт Google Workspace. Личные адреса не подойдут.
          </p>

          <a className={styles.googleLink} href={`${BASE_URL}/auth/login`}>
            <GoogleIcon className={styles.googleIcon} />
            Войти через Google
          </a>

          <div className={styles.divider}>
            <span className={styles.dividerLine} />
            <span className={styles.dividerLabel}>Доступ</span>
            <span className={styles.dividerLine} />
          </div>

          <div className={styles.infoBox}>
            <span className={styles.infoIcon}>ⓘ</span>
            <span className={styles.infoText}>
              Аккаунт создаёт администратор. Если вход не проходит — напишите в{' '}
              <a href={`mailto:${SYSADMIN_EMAIL}`}>SysAdmin | SFF</a> или в Telegram{' '}
              <a href={`https://t.me/${SYSADMIN_TELEGRAM}`}>@{SYSADMIN_TELEGRAM}</a>.
            </span>
          </div>
        </div>

        <div className={styles.footer}>© 2026 Screen Factory Florida · Внутреннее использование</div>
      </div>
    </div>
  );
}

function GoogleIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.874 2.684-6.615Z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18Z"
      />
      <path
        fill="#FBBC05"
        d="M3.964 10.706A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.706V4.962H.957A8.997 8.997 0 0 0 0 9c0 1.452.348 2.827.957 4.038l3.007-2.332Z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.962L3.964 7.294C4.672 5.167 6.656 3.58 9 3.58Z"
      />
    </svg>
  );
}
