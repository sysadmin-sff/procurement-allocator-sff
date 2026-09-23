import { Button } from './Button';
import styles from './OrderDeleteModal.module.css';

interface OrderDeleteModalProps {
  /** True if any OrderItem on this Order has confirmed_price or
   * received_price set — same irreversibility criterion as
   * OrderDraftConflictModal's has_confirmed_prices (ADR-0012 §1), computed
   * by the caller from the single Order already loaded on the page. */
  hasConfirmedPrices: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  submitting?: boolean;
}

/** Single-step confirmation for DELETE /orders/{order_id} — see ADR-0037
 * §4. Deliberately no second confirmation step (checkbox/text input): the
 * user is already looking at exactly the one Order they opened, unlike
 * OrderDraftConflictModal where a single click could affect several
 * suppliers at once. */
export function OrderDeleteModal({ hasConfirmedPrices, onConfirm, onCancel, submitting }: OrderDeleteModalProps) {
  return (
    <div className={styles.overlay} role="presentation">
      <div className={styles.modal} role="dialog" aria-modal="true">
        <div className={styles.title}>Удалить ордер? Это необратимо.</div>

        {hasConfirmedPrices && (
          <div className={styles.confirmedPriceWarning} role="alert">
            В этом ордере есть подтверждённые цены — они будут потеряны безвозвратно.
          </div>
        )}

        <div className={styles.actions}>
          <Button variant="ghost" disabled={submitting} onClick={onCancel}>
            Отмена
          </Button>
          <Button variant="danger" disabled={submitting} onClick={onConfirm}>
            Удалить
          </Button>
        </div>
      </div>
    </div>
  );
}
