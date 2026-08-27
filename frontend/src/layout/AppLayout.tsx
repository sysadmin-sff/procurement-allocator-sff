import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { authApi } from '../api/auth';
import { useCurrentUser } from '../auth/AuthContext';
import styles from './AppLayout.module.css';

/* Видны всем аутентифицированным (project/allocation/order/purchase_record —
   get_current_user, ADR-0024 §4). */
const NAV_ITEMS = [{ to: '/projects', label: 'Проекты' }];

/* admin-only целиком на backend (require_role("admin") на весь роутер,
   ADR-0024 §4) — ссылка скрывается полностью, не дизейблится, иначе
   employee кликает и видит "недостаточно прав" вместо рабочего экрана. */
const ADMIN_NAV_ITEMS = [
  { to: '/suppliers', label: 'Поставщики' },
  { to: '/materials', label: 'Материалы' },
  { to: '/users', label: 'Пользователи' },
];
/* Импорт прайс-листа запускается со страницы конкретного поставщика
   (SupplierDetailPage → "Прайс-лист") — нет отдельного списка импортов,
   поэтому нет и отдельного пункта верхней навигации. Сам /suppliers уже
   скрыт от employee выше, так что вложенный флоу тоже недостижим. */

export function AppLayout() {
  const user = useCurrentUser();
  const navigate = useNavigate();
  const navItems = user.role === 'admin' ? [...NAV_ITEMS, ...ADMIN_NAV_ITEMS] : NAV_ITEMS;

  async function handleLogout() {
    await authApi.logout();
    navigate('/login', { replace: true });
  }

  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <div className={styles.brand}>
          <img src="/logo-horizontal.svg" alt="Screen Factory Florida" className={styles.logo} />
          <span className={styles.brandSuffix}>· Закупки</span>
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
