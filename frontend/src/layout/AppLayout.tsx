import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { authApi } from '../api/auth';
import { useCurrentUser } from '../auth/AuthContext';
import { useMeasurementsAccess } from '../hooks/useMeasurementsAccess';
import styles from './AppLayout.module.css';

/* Права по ролям — ADR-0055 (поверх ADR-0024 §4). Сотрудник ведёт проекты,
   поставщиков (включая импорт прайс-листа со страницы поставщика),
   материалы и шаблоны. Сводная матрица «Цены», справочник категорий и
   пользователи — только admin: пункт скрывается полностью, а прямой
   переход на адрес отсекает RequireAdmin в App.tsx. Порядок пунктов один
   для обеих ролей, у employee просто нет adminOnly. */
const NAV_ITEMS = [
  { to: '/projects', label: 'Проекты', adminOnly: false },
  { to: '/suppliers', label: 'Поставщики', adminOnly: false },
  { to: '/materials', label: 'Материалы', adminOnly: false },
  { to: '/prices', label: 'Цены', adminOnly: true },
  { to: '/categories', label: 'Категории', adminOnly: true },
  { to: '/project-templates', label: 'Шаблоны', adminOnly: false },
  { to: '/users', label: 'Пользователи', adminOnly: true },
];

/* «Замеры» — только admin (ADR-0055). Пункт по-прежнему показывается по
   ответу /measurements/access, а не по роли: так он скрыт и при выключенном
   модуле (MEASUREMENTS_ENABLED=false). Любая ошибка — пункт скрыт. */
const MEASUREMENTS_NAV_ITEM = { to: '/measurements', label: 'Замеры' };

export function AppLayout() {
  const user = useCurrentUser();
  const navigate = useNavigate();
  const hasMeasurementsAccess = useMeasurementsAccess();
  const roleItems = NAV_ITEMS.filter((item) => user.role === 'admin' || !item.adminOnly);
  const navItems = hasMeasurementsAccess ? [...roleItems, MEASUREMENTS_NAV_ITEM] : roleItems;

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
