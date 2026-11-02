import { useState } from 'react';
import { Button } from './Button';
import styles from './OrderDraftConflictModal.module.css';
import type { OrderDraftConflict, SupplierDraftAction, SupplierWithExistingDrafts } from '../api/types';

interface OrderDraftConflictModalProps {
  conflict: OrderDraftConflict;
  /** Called with one action per conflicting supplier, keyed by supplier_id
   * — sent as supplier_actions (ADR-0048). */
  onSubmit: (actions: Record<string, SupplierDraftAction>) => void;
  onCancel: () => void;
  submitting?: boolean;
}

const ACTION_OPTIONS: { value: SupplierDraftAction; label: string }[] = [
  { value: 'replace', label: 'Заменить' },
  { value: 'add', label: 'Создать дополнительно' },
  { value: 'skip', label: 'Не создавать' },
];

function hasConfirmedPrices(supplier: SupplierWithExistingDrafts): boolean {
  return supplier.existing_draft_orders.some((o) => o.has_confirmed_prices);
}

/** Shown when POST .../orders returns 409 — see ADR-0012. Never opened
 * preemptively from client-side state; the backend's response is the only
 * source of truth for whether a conflict exists (ADR-0012 п.3). Each
 * conflicting supplier gets its own choice — replace its drafts, create an
 * additional Order next to them, or create nothing for it (ADR-0048), so a
 * recalculation for comparison doesn't duplicate suppliers that didn't
 * change. No preselection: none of the three is a safe default for every
 * supplier. */
export function OrderDraftConflictModal({ conflict, onSubmit, onCancel, submitting }: OrderDraftConflictModalProps) {
  const [actions, setActions] = useState<Record<string, SupplierDraftAction>>({});
  const [acknowledged, setAcknowledged] = useState(false);

  const suppliers = conflict.suppliers_with_existing_drafts;
  const allChosen = suppliers.every((s) => actions[s.supplier_id] != null);
  // The confirmed-price confirmation (ADR-0012 §4) only guards suppliers
  // actually being replaced — "add"/"skip" delete nothing.
  const requiresAcknowledgement = suppliers.some(
    (s) => actions[s.supplier_id] === 'replace' && hasConfirmedPrices(s),
  );
  const submitDisabled = submitting || !allChosen || (requiresAcknowledgement && !acknowledged);

  return (
    <div className={styles.overlay} role="presentation">
      <div className={styles.modal} role="dialog" aria-modal="true">
        <div className={styles.title}>По части поставщиков уже есть черновики ордеров</div>
        <p className={styles.intro}>
          Для этих поставщиков в проекте уже существуют черновики ордеров от прошлого расчёта.
          Выберите для каждого: заменить их текущим расчётом, создать новый ордер рядом со старыми
          или не создавать новый.
        </p>

        <div className={styles.supplierList}>
          {suppliers.map((supplier) => {
            const hasConfirmed = hasConfirmedPrices(supplier);
            const nameId = `draft-conflict-${supplier.supplier_id}`;
            return (
              <div key={supplier.supplier_id} className={styles.supplierRow}>
                <div id={nameId} className={styles.supplierName}>
                  {supplier.supplier_name}
                </div>
                <div className={styles.orderList}>
                  {supplier.existing_draft_orders.map((order) => (
                    <span key={order.order_id} className={styles.orderAmount}>
                      {formatMoney(order.total_amount)}
                    </span>
                  ))}
                </div>
                <div className={styles.actionGroup} role="radiogroup" aria-labelledby={nameId}>
                  {ACTION_OPTIONS.map((option) => (
                    <label key={option.value} className={styles.actionOption}>
                      <input
                        type="radio"
                        name={nameId}
                        value={option.value}
                        checked={actions[supplier.supplier_id] === option.value}
                        disabled={submitting}
                        onChange={() => setActions((prev) => ({ ...prev, [supplier.supplier_id]: option.value }))}
                      />
                      {option.label}
                    </label>
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
          «Заменить» удаляет старые черновики этого поставщика безвозвратно — необратимо меняет
          черновики проекта. Поставщики расчёта без старых черновиков создаются как обычно.
        </p>

        <div className={styles.actions}>
          <Button variant="ghost" disabled={submitting} onClick={onCancel}>
            Отмена
          </Button>
          <Button variant="primary" disabled={submitDisabled} onClick={() => onSubmit(actions)}>
            Создать ордера
          </Button>
        </div>
      </div>
    </div>
  );
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
