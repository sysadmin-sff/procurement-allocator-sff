import styles from '../../components/CrudScreen.module.css';

export interface DeliveryPolicyFormValues {
  flat_fee: string;
  free_shipping_enabled: boolean;
  free_shipping_threshold: string;
  per_order_min_amount: string;
  lead_time_days: string;
}

type DeliveryPolicyFieldKey = keyof DeliveryPolicyFormValues;
type DeliveryPolicyFieldValue = DeliveryPolicyFormValues[DeliveryPolicyFieldKey];

interface DeliveryPolicyFieldsProps {
  values: DeliveryPolicyFormValues;
  onChange: (key: DeliveryPolicyFieldKey, value: DeliveryPolicyFieldValue) => void;
  idPrefix: string;
}

/**
 * Delivery-policy inputs shared between the supplier create form and the
 * supplier detail page — kept as one component so the free_shipping_threshold
 * null-vs-0 distinction (ADR-0002: null = never free, 0 = always free) isn't
 * duplicated in two places that could drift out of sync.
 */
export function DeliveryPolicyFields({ values, onChange, idPrefix }: DeliveryPolicyFieldsProps) {
  return (
    <>
      <div className={styles.field}>
        <label className={styles.label} htmlFor={`${idPrefix}-flat-fee`}>
          Фиксированная ставка доставки
        </label>
        <input
          id={`${idPrefix}-flat-fee`}
          className={styles.input}
          type="number"
          min="0"
          step="0.01"
          value={values.flat_fee}
          onChange={(e) => onChange('flat_fee', e.target.value)}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.label} htmlFor={`${idPrefix}-min-order`}>
          Мин. сумма заказа
        </label>
        <input
          id={`${idPrefix}-min-order`}
          className={styles.input}
          type="number"
          min="0"
          step="0.01"
          value={values.per_order_min_amount}
          onChange={(e) => onChange('per_order_min_amount', e.target.value)}
        />
      </div>

      <div className={`${styles.field} ${styles.fieldFull}`}>
        <div className={styles.checkboxField}>
          <input
            id={`${idPrefix}-free-shipping-enabled`}
            type="checkbox"
            checked={values.free_shipping_enabled}
            onChange={(e) => onChange('free_shipping_enabled', e.target.checked)}
          />
          <label className={styles.checkboxLabel} htmlFor={`${idPrefix}-free-shipping-enabled`}>
            Бесплатная доставка настроена
          </label>
        </div>
        <div className={styles.fieldHint}>
          Не отмечено → порог бесплатной доставки не задан (доставка никогда не бесплатна).
          Отмечено → можно указать порог, включая $0 (бесплатно всегда).
        </div>
      </div>

      <div className={styles.field}>
        <label className={styles.label} htmlFor={`${idPrefix}-threshold`}>
          Порог бесплатной доставки
        </label>
        <input
          id={`${idPrefix}-threshold`}
          className={styles.input}
          type="number"
          min="0"
          step="0.01"
          disabled={!values.free_shipping_enabled}
          value={values.free_shipping_threshold}
          onChange={(e) => onChange('free_shipping_threshold', e.target.value)}
        />
      </div>

      <div className={styles.field}>
        <label className={styles.label} htmlFor={`${idPrefix}-lead-time`}>
          Срок поставки, дней
        </label>
        <input
          id={`${idPrefix}-lead-time`}
          className={styles.input}
          type="number"
          min="0"
          step="1"
          value={values.lead_time_days}
          onChange={(e) => onChange('lead_time_days', e.target.value)}
        />
      </div>
    </>
  );
}

export function deliveryPolicyToFormValues(policy?: {
  flat_fee: number;
  free_shipping_threshold: number | null;
  per_order_min_amount: number;
  lead_time_days: number;
}): DeliveryPolicyFormValues {
  return {
    flat_fee: String(policy?.flat_fee ?? 0),
    free_shipping_enabled: policy?.free_shipping_threshold !== null && policy !== undefined,
    free_shipping_threshold:
      policy?.free_shipping_threshold != null ? String(policy.free_shipping_threshold) : '0',
    per_order_min_amount: String(policy?.per_order_min_amount ?? 0),
    lead_time_days: String(policy?.lead_time_days ?? 0),
  };
}

export function formValuesToDeliveryPolicy(values: DeliveryPolicyFormValues) {
  return {
    flat_fee: Number(values.flat_fee) || 0,
    free_shipping_threshold: values.free_shipping_enabled
      ? Number(values.free_shipping_threshold) || 0
      : null,
    per_order_min_amount: Number(values.per_order_min_amount) || 0,
    lead_time_days: Number(values.lead_time_days) || 0,
  };
}
