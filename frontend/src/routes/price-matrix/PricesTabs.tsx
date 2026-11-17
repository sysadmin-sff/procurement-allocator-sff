import { NavLink } from 'react-router-dom';
import styles from './PriceMatrix.module.css';

/** Вкладки раздела «Цены»: матрица (ADR-0054) и динамика (ADR-0057). */
export function PricesTabs() {
  const tabClass = ({ isActive }: { isActive: boolean }) =>
    isActive ? `${styles.tab} ${styles.tabActive}` : styles.tab;
  return (
    <nav className={styles.tabs} aria-label="Разделы цен">
      <NavLink to="/prices" end className={tabClass}>
        Таблица цен
      </NavLink>
      <NavLink to="/prices/dynamics" className={tabClass}>
        Динамика
      </NavLink>
    </nav>
  );
}
