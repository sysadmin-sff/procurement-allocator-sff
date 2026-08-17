import { NavLink, Outlet } from 'react-router-dom';
import styles from './AppLayout.module.css';

const NAV_ITEMS = [
  { to: '/projects', label: 'Проекты' },
  { to: '/price-review', label: 'Импорт прайс-листов' },
  { to: '/materials', label: 'Материалы' },
  { to: '/suppliers', label: 'Поставщики' },
];

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
