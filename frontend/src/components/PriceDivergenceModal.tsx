import { Button } from './Button';
import styles from './PriceDivergenceModal.module.css';
import type { PriceDivergence } from '../api/types';

interface PriceDivergenceModalProps {
  divergence: PriceDivergence;
  materialName: string;
  supplierName: string;
  onConfirm: () => void;
  onDismiss: () => void;
  submitting?: boolean;
}

/** Single-row popup shown right after an inline confirmed_price PATCH whose
 * response carried price_divergence — see ADR-0030 п.4.2. confirmed_price on
 * the OrderItem is already saved by the time this renders; declining here
 * (or closing without a choice) does not roll it back — see ADR-0030 п.7. */
export function PriceDivergenceModal({
  divergence,
  materialName,
  supplierName,
  onConfirm,
  onDismiss,
  submitting,
}: PriceDivergenceModalProps) {
  return (
    <div className={styles.overlay} role="presentation">
      <div className={styles.modal} role="dialog" aria-modal="true">
        <div className={styles.title}>
          {divergence.action === 'create' ? 'Добавить цену в справочник?' : 'Обновить цену в справочнике?'}
        </div>
        <p className={styles.intro}>
          {divergence.action === 'create'
            ? 'Для этой пары материал/поставщик в справочнике ещё нет записи. Сохранить только что подтверждённую цену как новую?'
            : 'Подтверждённая цена отличается от той, что сейчас в справочнике. Обновить справочник этой ценой?'}
        </p>

        <div className={styles.summary}>
          <div className={styles.materialName}>{materialName}</div>
          <div className={styles.supplierName}>{supplierName}</div>
          <div className={styles.priceRow}>
            <span className={styles.priceLabel}>Сейчас в базе:</span>{' '}
            {divergence.current_price != null ? (
              <span className={styles.currentPrice}>{formatMoney(divergence.current_price)}</span>
            ) : (
              <span className={styles.noActivePrice}>нет активной цены</span>
            )}
          </div>
          <div className={styles.priceRow}>
            <span className={styles.priceLabel}>Подтверждено:</span>{' '}
            <span className={styles.newPrice}>{formatMoney(divergence.confirmed_price)}</span>
          </div>
        </div>

        <div className={styles.actions}>
          <Button variant="ghost" disabled={submitting} onClick={onDismiss}>
            Не обновлять
          </Button>
          <Button variant="primary" disabled={submitting} onClick={onConfirm}>
            {submitting ? 'Обновляем…' : 'Обновить цену в базе'}
          </Button>
        </div>
      </div>
    </div>
  );
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
