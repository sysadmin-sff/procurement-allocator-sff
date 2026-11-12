import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { pricesApi } from '../../api/prices';
import type { PriceHistoryEntry } from '../../api/types';
import crudStyles from '../../components/CrudScreen.module.css';
import { formatDate, formatMoney } from './format';
import styles from './PriceMatrix.module.css';

const POPUP_WIDTH = 380;

/**
 * История пары материал + поставщик (GET /prices/history, ADR-0054 §6).
 * Тот же приём, что у PriceHistoryIndicator на OrderDetailPage: портал в
 * body с position: fixed, чтобы попап не обрезал скролл-контейнер матрицы.
 * Закрывается кликом вне, Esc и прокруткой (координаты якоря устаревают).
 */
export function PriceHistoryPopover({
  materialId,
  materialName,
  supplierId,
  supplierName,
  anchor,
  onClose,
}: {
  materialId: string;
  materialName: string;
  supplierId: string;
  supplierName: string;
  anchor: DOMRect;
  onClose: () => void;
}) {
  const [history, setHistory] = useState<PriceHistoryEntry[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    pricesApi
      .history(materialId, supplierId)
      .then((data) => {
        if (!cancelled) setHistory(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err);
      });
    return () => {
      cancelled = true;
    };
  }, [materialId, supplierId]);

  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) onClose();
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    function handleScroll(e: Event) {
      if (popupRef.current && popupRef.current.contains(e.target as Node)) return;
      onClose();
    }
    document.addEventListener('mousedown', handleMouseDown);
    document.addEventListener('keydown', handleKey);
    window.addEventListener('scroll', handleScroll, true);
    return () => {
      document.removeEventListener('mousedown', handleMouseDown);
      document.removeEventListener('keydown', handleKey);
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, [onClose]);

  const left = Math.max(8, Math.min(anchor.left, window.innerWidth - POPUP_WIDTH - 8));
  const openUp = anchor.bottom + 320 > window.innerHeight && anchor.top > 320;
  const style: CSSProperties = openUp
    ? { position: 'fixed', left, bottom: window.innerHeight - anchor.top + 4, width: POPUP_WIDTH }
    : { position: 'fixed', left, top: anchor.bottom + 4, width: POPUP_WIDTH };

  return createPortal(
    <div ref={popupRef} className={styles.historyPopup} style={style} role="dialog" aria-label="История цены">
      <div className={styles.historyHeader}>
        <div className={styles.historyTitle}>{supplierName}</div>
        <div className={styles.historySubtitle}>{materialName}</div>
      </div>
      {error != null && <div className={styles.historyMuted}>Не удалось загрузить историю цены.</div>}
      {history == null && error == null && <div className={styles.historyMuted}>Загрузка…</div>}
      {history != null && (
        <ul className={styles.historyList}>
          {history.map((entry) => {
            const isActive = entry.valid_to == null;
            const valueClass =
              entry.change === 'down' ? styles.cellDown : entry.change === 'up' ? styles.cellUp : '';
            return (
              <li key={entry.id} className={styles.historyRow}>
                <span className={`${styles.historyValue} ${valueClass}`}>
                  {formatMoney(entry.price)}
                  {entry.change === 'down' && ' ▼'}
                  {entry.change === 'up' && ' ▲'}
                </span>
                <span className={styles.historyDates}>
                  {formatDate(entry.valid_from)} — {entry.valid_to ? formatDate(entry.valid_to) : 'сейчас'}
                </span>
                <span
                  className={`${crudStyles.badge} ${isActive ? crudStyles.badgeActive : crudStyles.badgeHistorical}`}
                >
                  {isActive ? 'активна' : 'историческая'}
                </span>
                <span className={styles.historySource}>
                  <SourceLabel entry={entry} />
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>,
    document.body,
  );
}

function SourceLabel({ entry }: { entry: PriceHistoryEntry }) {
  if (entry.source === 'order') {
    return (
      <>
        из ордера{' '}
        {entry.order_id ? (
          <Link to={`/orders/${entry.order_id}`} className={styles.historyLink}>
            {entry.order_title ?? 'открыть'}
          </Link>
        ) : null}
        {entry.created_by_name && ` · ${entry.created_by_name}`}
      </>
    );
  }
  if (entry.source === 'import') {
    return (
      <>
        прайс-лист
        {entry.import_uploaded_at && ` от ${formatDate(entry.import_uploaded_at)}`}
      </>
    );
  }
  return <>вручную{entry.created_by_name && ` · ${entry.created_by_name}`}</>;
}
