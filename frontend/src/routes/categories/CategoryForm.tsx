import { useState } from 'react';
import type { FormEvent } from 'react';
import { Button } from '../../components/Button';
import type { Category, CategoryCreate } from '../../api/types';
import styles from '../../components/CrudScreen.module.css';

interface CategoryFormProps {
  initial?: Category;
  onCancel: () => void;
  onSubmit: (payload: Required<CategoryCreate>) => Promise<void>;
}

export function CategoryForm({ initial, onCancel, onSubmit }: CategoryFormProps) {
  const [name, setName] = useState(initial?.name ?? '');
  const [skuPrefix, setSkuPrefix] = useState(initial?.sku_prefix ?? '');
  const [requiresSingleSupplier, setRequiresSingleSupplier] = useState(
    initial?.requires_single_supplier ?? false,
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (!name.trim() || (!initial && !skuPrefix.trim())) {
      setError('Название и sku_prefix обязательны');
      return;
    }

    setSubmitting(true);
    try {
      await onSubmit({
        name: name.trim(),
        sku_prefix: skuPrefix.trim(),
        requires_single_supplier: requiresSingleSupplier,
      });
    } catch {
      // ApiError surfaces via the parent's error state; keep the form open to retry.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className={styles.cardPadded} onSubmit={handleSubmit}>
      {!initial && (
        <div className={`${styles.warningBanner} ${styles.formBanner}`}>
          sku_prefix нельзя изменить после создания категории — он неизменяем, потому что уже
          выданные internal_sku материалов содержат его как часть значения (см. ADR-0034 §5).
          Убедитесь, что вводите правильный префикс сейчас.
        </div>
      )}

      <div className={styles.formGrid}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="category-name">
            Название
          </label>
          <input
            id="category-name"
            className={styles.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="category-sku-prefix">
            sku_prefix
          </label>
          {initial ? (
            <input
              id="category-sku-prefix"
              className={styles.input}
              value={skuPrefix}
              disabled
              readOnly
            />
          ) : (
            <input
              id="category-sku-prefix"
              className={styles.input}
              value={skuPrefix}
              onChange={(e) => setSkuPrefix(e.target.value)}
              required
            />
          )}
          {initial && <div className={styles.fieldHint}>Неизменяем после создания.</div>}
        </div>

        <div className={`${styles.field} ${styles.fieldFull}`}>
          <div className={styles.checkboxField}>
            <input
              id="category-requires-single-supplier"
              type="checkbox"
              checked={requiresSingleSupplier}
              onChange={(e) => setRequiresSingleSupplier(e.target.checked)}
            />
            <label className={styles.checkboxLabel} htmlFor="category-requires-single-supplier">
              Требует одного поставщика на весь проект (строгая категория)
            </label>
          </div>
        </div>
      </div>

      {error && <div className={styles.fieldError}>{error}</div>}

      <div className={styles.formActions}>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={submitting}>
          Отмена
        </Button>
        <Button type="submit" variant="primary" disabled={submitting}>
          {initial ? 'Сохранить' : 'Добавить категорию'}
        </Button>
      </div>
    </form>
  );
}
