import { useState } from 'react';
import { Button } from './Button';
import styles from './OrderDraftConflictModal.module.css';
import type { OrderDraftConflict, SupplierWithExistingDrafts } from '../api/types';

interface OrderDraftConflictModalProps {
  conflict: OrderDraftConflict;
  onReplace: () => void;
  onCancel: () => void;
  submitting?: boolean;
}

function hasConfirmedPrices(supplier: SupplierWithExistingDrafts): boolean {
  return supplier.existing_draft_orders.some((o) => o.has_confirmed_prices);
}

/** Shown when POST .../orders returns 409 — see ADR-0012. Never opened
 * preemptively from client-side state; the backend's response is the only
 * source of truth for whether a conflict exists (ADR-0012 п.3). */
export function OrderDraftConflictModal({
  conflict,
  onReplace,
  onCancel,
  submitting,
}: OrderDraftConflictModalProps) {
  const requiresAcknowledgement = conflict.suppliers_with_existing_drafts.some(hasConfirmedPrices);
  const [acknowledged, setAcknowledged] = useState(false);

  const replaceDisabled = submitting || (requiresAcknowledgement && !acknowledged);

  return (
    <div className={styles.overlay} role="presentation">
      <div className={styles.modal} role="dialog" aria-modal="true">
        <div className={styles.title}>По части поставщиков уже есть черновики ордеров</div>
        <p className={styles.intro}>
          Для этих поставщиков в проекте уже существуют черновики ордеров от прошлого расчёта.
          Замените их текущим расчётом, или отмените и решите по каждому поставщику отдельно.
        </p>

        <div className={styles.supplierList}>
          {conflict.suppliers_with_existing_drafts.map((supplier) => {
            const hasConfirmed = hasConfirmedPrices(supplier);
            return (
              <div key={supplier.supplier_id} className={styles.supplierRow}>
                <div className={styles.supplierName}>{supplier.supplier_name}</div>
                <div className={styles.orderList}>
                  {supplier.existing_draft_orders.map((order) => (
                    <span key={order.order_id} className={styles.orderAmount}>
                      {formatMoney(order.total_amount)}
                    </span>
                  ))}
                </div>
                {hasConfirmed && (
                  <div className={styles.confirmedPriceWarning} role="alert">
                    ⚠ в этом черновике уже есть подтверждённые поставщиком цены — они будут
                    потеряны при замене.
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {requiresAcknowledgement && (
          <label className={styles.acknowledgeRow}>
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />
            Да, я понимаю, что подтверждённые цены будут потеряны, и хочу заменить черновики
          </label>
        )}

        <p className={styles.footerHint}>
          Замена удалит старые черновики безвозвратно — необратимо меняет черновики этого
          проекта.
        </p>

        <div className={styles.actions}>
          <Button variant="ghost" disabled={submitting} onClick={onCancel}>
            Отмена
          </Button>
          <Button variant="danger" disabled={replaceDisabled} onClick={onReplace}>
            Заменить черновики
          </Button>
        </div>
      </div>
    </div>
  );
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
