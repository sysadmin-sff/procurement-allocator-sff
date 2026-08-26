import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { authApi } from '../api/auth';
import { useCurrentUser } from '../auth/AuthContext';
import styles from './AppLayout.module.css';

const NAV_ITEMS = [
  { to: '/projects', label: 'Проекты' },
  { to: '/suppliers', label: 'Поставщики' },
  { to: '/materials', label: 'Материалы' },
];
/* Импорт прайс-листа запускается со страницы конкретного поставщика
   (SupplierDetailPage → "Прайс-лист") — нет отдельного списка импортов,
   поэтому нет и отдельного пункта верхней навигации. */

export function AppLayout() {
  const user = useCurrentUser();
  const navigate = useNavigate();
  const navItems =
    user.role === 'admin' ? [...NAV_ITEMS, { to: '/users', label: 'Пользователи' }] : NAV_ITEMS;

  async function handleLogout() {
    await authApi.logout();
    navigate('/login', { replace: true });
  }

  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <div className={styles.brand}>
          <span className={styles.logo}>SF</span>
          <span className={styles.brandName}>
            SCREEN FACTORY <span className={styles.brandSuffix}>· Закупки</span>
          </span>
        </div>
        <div className={styles.divider} />
        <nav className={styles.nav}>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? styles.navItemActive : styles.navItem)}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className={styles.userBlock}>
          <div className={styles.userInfo}>
            <span className={styles.userName}>{user.name ?? user.email}</span>
            <span className={styles.userEmail}>{user.email}</span>
          </div>
          <button type="button" className={styles.logoutButton} onClick={() => void handleLogout()}>
            Выйти
          </button>
        </div>
      </header>
      <main className={styles.content}>
        <Outlet />
      </main>
    </div>
  );
}
