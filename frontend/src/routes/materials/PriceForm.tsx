import { useState } from 'react';
import type { FormEvent } from 'react';
import { Button } from '../../components/Button';
import type { Price, PriceCreate, PriceUpdate, Supplier } from '../../api/types';
import styles from '../../components/CrudScreen.module.css';

interface PriceFormProps {
  materialId: string;
  suppliers: Supplier[];
  initial?: Price;
  onCancel: () => void;
  onSubmitCreate?: (payload: PriceCreate) => Promise<void>;
  onSubmitUpdate?: (payload: PriceUpdate) => Promise<void>;
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function PriceForm({
  materialId,
  suppliers,
  initial,
  onCancel,
  onSubmitCreate,
  onSubmitUpdate,
}: PriceFormProps) {
  const [supplierId, setSupplierId] = useState(initial?.supplier_id ?? suppliers[0]?.id ?? '');
  const [price, setPrice] = useState(initial ? String(initial.price) : '');
  const [availability, setAvailability] = useState(
    initial?.availability != null ? String(initial.availability) : '',
  );
  const [minOrderQty, setMinOrderQty] = useState(
    initial?.min_order_qty != null ? String(initial.min_order_qty) : '',
  );
  const [validFrom, setValidFrom] = useState(initial?.valid_from ?? today());
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (!supplierId) {
      setError('Выберите поставщика');
      return;
    }
    const priceValue = Number(price);
    if (!price || Number.isNaN(priceValue) || priceValue < 0) {
      setError('Цена обязательна и не может быть отрицательной');
      return;
    }
    const availabilityValue = availability === '' ? null : Number(availability);
    if (availabilityValue !== null && (Number.isNaN(availabilityValue) || availabilityValue < 0)) {
      setError('Наличие не может быть отрицательным');
      return;
    }
    const minOrderQtyValue = minOrderQty === '' ? null : Number(minOrderQty);
    if (minOrderQtyValue !== null && (Number.isNaN(minOrderQtyValue) || minOrderQtyValue < 0)) {
      setError('Мин. количество заказа не может быть отрицательным');
      return;
    }
    if (!validFrom) {
      setError('Дата начала действия обязательна');
      return;
    }

    setSubmitting(true);
    try {
      if (initial && onSubmitUpdate) {
        await onSubmitUpdate({
          price: priceValue,
          availability: availabilityValue,
          min_order_qty: minOrderQtyValue,
          valid_from: validFrom,
        });
      } else if (onSubmitCreate) {
        await onSubmitCreate({
          material_id: materialId,
          supplier_id: supplierId,
          price: priceValue,
          availability: availabilityValue,
          min_order_qty: minOrderQtyValue,
          valid_from: validFrom,
        });
      }
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
          <label className={styles.label} htmlFor="price-supplier">
            Поставщик
          </label>
          <select
            id="price-supplier"
            className={styles.select}
            value={supplierId}
            onChange={(e) => setSupplierId(e.target.value)}
            disabled={Boolean(initial)}
            required
          >
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="price-value">
            Цена
          </label>
          <input
            id="price-value"
            className={styles.input}
            type="number"
            min="0"
            step="0.01"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            required
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="price-availability">
            Наличие
          </label>
          <input
            id="price-availability"
            className={styles.input}
            type="number"
            min="0"
            step="1"
            value={availability}
            onChange={(e) => setAvailability(e.target.value)}
            placeholder="не ограничено"
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="price-min-order-qty">
            Мин. кол-во заказа
          </label>
          <input
            id="price-min-order-qty"
            className={styles.input}
            type="number"
            min="0"
            step="1"
            value={minOrderQty}
            onChange={(e) => setMinOrderQty(e.target.value)}
            placeholder="без ограничения"
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="price-valid-from">
            Действует с
          </label>
          <input
            id="price-valid-from"
            className={styles.input}
            type="date"
            value={validFrom}
            onChange={(e) => setValidFrom(e.target.value)}
            required
          />
        </div>
      </div>

      {error && <div className={styles.fieldError}>{error}</div>}

      <div className={styles.formActions}>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={submitting}>
          Отмена
        </Button>
        <Button type="submit" variant="primary" disabled={submitting}>
          {initial ? 'Сохранить цену' : 'Добавить цену'}
        </Button>
      </div>
    </form>
  );
}
