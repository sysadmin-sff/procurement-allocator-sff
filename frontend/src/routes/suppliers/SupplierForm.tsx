import { useState } from 'react';
import type { FormEvent } from 'react';
import { Button } from '../../components/Button';
import type { DeliveryPolicy, Supplier, SupplierCreate } from '../../api/types';
import {
  DeliveryPolicyFields,
  deliveryPolicyToFormValues,
  formValuesToDeliveryPolicy,
  type DeliveryPolicyFormValues,
} from './DeliveryPolicyFields';
import styles from '../../components/CrudScreen.module.css';

export interface SupplierFormValues extends DeliveryPolicyFormValues {
  name: string;
  contacts: string;
  currency: string;
}

interface SupplierFormProps {
  initial?: Supplier;
  onCancel: () => void;
  onSubmit: (payload: Required<SupplierCreate>) => Promise<void>;
}

function toFormValues(supplier?: Supplier): SupplierFormValues {
  return {
    name: supplier?.name ?? '',
    contacts: supplier?.contacts ?? '',
    currency: supplier?.currency ?? 'USD',
    ...deliveryPolicyToFormValues(supplier?.delivery_policy),
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

    const delivery_policy: DeliveryPolicy = formValuesToDeliveryPolicy(values);

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

        <DeliveryPolicyFields values={values} onChange={update} idPrefix="supplier" />
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
