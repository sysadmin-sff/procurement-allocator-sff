import { useState } from 'react';
import type { FormEvent } from 'react';
import { Button } from '../../components/Button';
import type { DeliveryPolicy, Supplier, SupplierCreate } from '../../api/types';
import styles from '../../components/CrudScreen.module.css';

export interface SupplierFormValues {
  name: string;
  contacts: string;
  currency: string;
  flat_fee: string;
  free_shipping_enabled: boolean;
  free_shipping_threshold: string;
  per_order_min_amount: string;
  lead_time_days: string;
}

interface SupplierFormProps {
  initial?: Supplier;
  onCancel: () => void;
  onSubmit: (payload: Required<SupplierCreate>) => Promise<void>;
}

function toFormValues(supplier?: Supplier): SupplierFormValues {
  const policy = supplier?.delivery_policy;
  return {
    name: supplier?.name ?? '',
    contacts: supplier?.contacts ?? '',
    currency: supplier?.currency ?? 'USD',
    flat_fee: String(policy?.flat_fee ?? 0),
    free_shipping_enabled: policy?.free_shipping_threshold !== null && policy !== undefined,
    free_shipping_threshold:
      policy?.free_shipping_threshold != null ? String(policy.free_shipping_threshold) : '0',
    per_order_min_amount: String(policy?.per_order_min_amount ?? 0),
    lead_time_days: String(policy?.lead_time_days ?? 0),
  };
}

export function SupplierForm({ initial, onCancel, onSubmit }: SupplierFormProps) {
  const [values, setValues] = useState<SupplierFormValues>(() => toFormValues(initial));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function update<K extends keyof SupplierFormValues>(key: K, value: SupplierFormValues[K]) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (!values.name.trim()) {
      setError('Название поставщика обязательно');
      return;
    }

    const delivery_policy: DeliveryPolicy = {
      flat_fee: Number(values.flat_fee) || 0,
      free_shipping_threshold: values.free_shipping_enabled
        ? Number(values.free_shipping_threshold) || 0
        : null,
      per_order_min_amount: Number(values.per_order_min_amount) || 0,
      lead_time_days: Number(values.lead_time_days) || 0,
    };

    setSubmitting(true);
    try {
      await onSubmit({
        name: values.name.trim(),
        contacts: values.contacts.trim() || null,
        currency: values.currency.trim() || 'USD',
        delivery_policy,
      });
    } catch {
      // ApiError surfaces via the parent's error state; keep the form open to retry.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className={styles.cardPadded} onSubmit={handleSubmit}>
      <div className={styles.formGrid}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="supplier-name">
            Название
          </label>
          <input
            id="supplier-name"
            className={styles.input}
            value={values.name}
            onChange={(e) => update('name', e.target.value)}
            required
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="supplier-currency">
            Валюта
          </label>
          <input
            id="supplier-currency"
            className={styles.input}
            value={values.currency}
            onChange={(e) => update('currency', e.target.value)}
          />
        </div>
        <div className={`${styles.field} ${styles.fieldFull}`}>
          <label className={styles.label} htmlFor="supplier-contacts">
            Контакты
          </label>
          <input
            id="supplier-contacts"
            className={styles.input}
            value={values.contacts}
            onChange={(e) => update('contacts', e.target.value)}
            placeholder="Email, телефон…"
          />
        </div>

        <div className={`${styles.field} ${styles.fieldFull}`}>
          <div className={styles.sectionTitle}>Политика доставки</div>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="supplier-flat-fee">
            Фиксированная ставка доставки
          </label>
          <input
            id="supplier-flat-fee"
            className={styles.input}
            type="number"
            min="0"
            step="0.01"
            value={values.flat_fee}
            onChange={(e) => update('flat_fee', e.target.value)}
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="supplier-min-order">
            Мин. сумма заказа
          </label>
          <input
            id="supplier-min-order"
            className={styles.input}
            type="number"
            min="0"
            step="0.01"
            value={values.per_order_min_amount}
            onChange={(e) => update('per_order_min_amount', e.target.value)}
          />
        </div>

        <div className={`${styles.field} ${styles.fieldFull}`}>
          <div className={styles.checkboxField}>
            <input
              id="supplier-free-shipping-enabled"
              type="checkbox"
              checked={values.free_shipping_enabled}
              onChange={(e) => update('free_shipping_enabled', e.target.checked)}
            />
            <label className={styles.checkboxLabel} htmlFor="supplier-free-shipping-enabled">
              Бесплатная доставка настроена
            </label>
          </div>
          <div className={styles.fieldHint}>
            Не отмечено → порог бесплатной доставки не задан (доставка никогда не бесплатна).
            Отмечено → можно указать порог, включая $0 (бесплатно всегда).
          </div>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="supplier-threshold">
            Порог бесплатной доставки
          </label>
          <input
            id="supplier-threshold"
            className={styles.input}
            type="number"
            min="0"
            step="0.01"
            disabled={!values.free_shipping_enabled}
            value={values.free_shipping_threshold}
            onChange={(e) => update('free_shipping_threshold', e.target.value)}
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="supplier-lead-time">
            Срок поставки, дней
          </label>
          <input
            id="supplier-lead-time"
            className={styles.input}
            type="number"
            min="0"
            step="1"
            value={values.lead_time_days}
            onChange={(e) => update('lead_time_days', e.target.value)}
          />
        </div>
      </div>

      {error && <div className={styles.fieldError}>{error}</div>}

      <div className={styles.formActions}>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={submitting}>
          Отмена
        </Button>
        <Button type="submit" variant="primary" disabled={submitting}>
          {initial ? 'Сохранить' : 'Добавить поставщика'}
        </Button>
      </div>
    </form>
  );
}
