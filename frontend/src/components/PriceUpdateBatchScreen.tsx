import { useState } from 'react';
import { Button } from './Button';
import styles from './PriceUpdateBatchScreen.module.css';
import type { PriceDivergence, PriceUpdateResult, PriceUpdateSelection } from '../api/types';

export interface PriceUpdateBatchRow {
  order_item_id: string;
  divergence: PriceDivergence;
  materialName: string;
  supplierName: string;
}

interface PriceUpdateBatchScreenProps {
  rows: PriceUpdateBatchRow[];
  results: PriceUpdateResult[] | null;
  onSubmit: (selections: PriceUpdateSelection[]) => void;
  submitting?: boolean;
}

/** Separate step shown after a batch confirmed_price application
 * (handleApplyAllMatched, ADR-0027 §2) when at least one applied row
 * diverged from the active Price — see ADR-0030 п.4.3. Only the divergent
 * rows appear here, not every applied row; confirmed_price on every
 * OrderItem is already saved regardless of what happens on this screen
 * (ADR-0030 п.7).
 *
 * Checkboxes default unchecked (ADR-0030 п.4 "Обоснование"): applying the
 * batch already asked the employee to trust the parsed results wholesale
 * ("Применить все совпадения") — writing to the shared Price catalog is a
 * heavier, qualitatively different action (it affects every future
 * allocation across every project, not just this Order), so it gets a more
 * conservative default than the rest of this screen's checkboxes. */
export function PriceUpdateBatchScreen({ rows, results, onSubmit, submitting }: PriceUpdateBatchScreenProps) {
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const resultByItemId = new Map((results ?? []).map((r) => [r.order_item_id, r]));

  function handleSubmit() {
    onSubmit(rows.map((row) => ({ order_item_id: row.order_item_id, apply: checked[row.order_item_id] ?? false })));
  }

  return (
    <div className={styles.section}>
      <div className={styles.title}>Расхождения со справочником цен ({rows.length})</div>
      <p className={styles.intro}>
        У этих позиций подтверждённая цена отличается от активной цены в справочнике (или записи ещё
        нет). Отметьте, какие цены обновить в базе — по умолчанию ничего не выбрано.
      </p>

      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.checkboxCell} />
            <th>Материал / поставщик</th>
            <th className={styles.numCell}>Сейчас в базе</th>
            <th className={styles.numCell}>Подтверждено</th>
            <th>Результат</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const result = resultByItemId.get(row.order_item_id);
            return (
              <tr key={row.order_item_id}>
                <td className={styles.checkboxCell}>
                  <input
                    type="checkbox"
                    checked={checked[row.order_item_id] ?? false}
                    disabled={submitting}
                    onChange={(e) =>
                      setChecked((prev) => ({ ...prev, [row.order_item_id]: e.target.checked }))
                    }
                  />
                </td>
                <td>
                  <div className={styles.materialCell}>
                    <span>{row.materialName}</span>
                    <span className={styles.supplierName}>{row.supplierName}</span>
                  </div>
                </td>
                <td className={styles.numCell}>
                  {row.divergence.current_price != null ? (
                    formatMoney(row.divergence.current_price)
                  ) : (
                    <span className={styles.noActivePrice}>нет активной цены</span>
                  )}
                </td>
                <td className={styles.numCell}>
                  <span className={styles.newPrice}>{formatMoney(row.divergence.confirmed_price)}</span>
                </td>
                <td>
                  {result &&
                    (result.applied ? (
                      <span className={`${styles.resultRow} ${styles.resultApplied}`}>
                        Обновлено ({result.action === 'create' ? 'создана новая запись' : 'цена обновлена'})
                      </span>
                    ) : (
                      <span className={`${styles.resultRow} ${styles.resultError}`}>
                        {result.error ?? 'Не применено'}
                      </span>
                    ))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className={styles.actions}>
        <Button variant="primary" disabled={submitting} onClick={handleSubmit}>
          {submitting ? 'Обновляем…' : 'Обновить выбранные цены в базе'}
        </Button>
      </div>
    </div>
  );
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
