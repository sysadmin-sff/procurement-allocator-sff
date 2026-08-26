import { NavLink, Outlet } from 'react-router-dom';
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
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? styles.navItemActive : styles.navItem)}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className={styles.content}>
        <Outlet />
      </main>
    </div>
  );
}
