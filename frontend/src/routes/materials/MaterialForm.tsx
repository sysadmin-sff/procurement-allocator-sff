import { useState } from 'react';
import type { FormEvent } from 'react';
import { Button } from '../../components/Button';
import type { Material, MaterialCreate } from '../../api/types';
import styles from '../../components/CrudScreen.module.css';

interface MaterialFormProps {
  initial?: Material;
  onCancel: () => void;
  onSubmit: (payload: MaterialCreate) => Promise<void>;
}

function toAttributesText(material?: Material): string {
  if (!material || Object.keys(material.attributes).length === 0) return '{}';
  return JSON.stringify(material.attributes, null, 2);
}

export function MaterialForm({ initial, onCancel, onSubmit }: MaterialFormProps) {
  const [internalSku, setInternalSku] = useState(initial?.internal_sku ?? '');
  const [canonicalName, setCanonicalName] = useState(initial?.canonical_name ?? '');
  const [category, setCategory] = useState(initial?.category ?? '');
  const [unit, setUnit] = useState(initial?.unit ?? '');
  const [attributesText, setAttributesText] = useState(() => toAttributesText(initial));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const skuChanged = initial != null && internalSku.trim() !== initial.internal_sku;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (!internalSku.trim() || !canonicalName.trim() || !unit.trim()) {
      setError('internal_sku, название и единица измерения обязательны');
      return;
    }

    let attributes: Record<string, unknown>;
    try {
      attributes = attributesText.trim() ? JSON.parse(attributesText) : {};
      if (typeof attributes !== 'object' || attributes === null || Array.isArray(attributes)) {
        throw new Error('not an object');
      }
    } catch {
      setError('Атрибуты должны быть валидным JSON-объектом, например {"width": 96}');
      return;
    }

    setSubmitting(true);
    try {
      await onSubmit({
        internal_sku: internalSku.trim(),
        canonical_name: canonicalName.trim(),
        category: category.trim() || null,
        unit: unit.trim(),
        attributes,
      });
    } catch {
      // ApiError surfaces via the parent's error state; keep the form open to retry.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className={styles.cardPadded} onSubmit={handleSubmit}>
      {initial && (
        <div className={`${styles.warningBanner} ${styles.formBanner}`}>
          internal_sku — ключ идентичности материала (см. CLAUDE.md): по нему связаны цены и
          позиции проектов. Меняйте только если это действительно исправление ошибки ввода, не
          переименование товара.
        </div>
      )}

      <div className={styles.formGrid}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="material-sku">
            internal_sku
          </label>
          <input
            id="material-sku"
            className={styles.input}
            value={internalSku}
            onChange={(e) => setInternalSku(e.target.value)}
            required
          />
          {skuChanged && (
            <div className={styles.fieldError}>
              Изменение internal_sku переопределяет идентичность материала — убедитесь, что это
              осознанно.
            </div>
          )}
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="material-unit">
            Единица измерения
          </label>
          <input
            id="material-unit"
            className={styles.input}
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            placeholder="шт, рул., ft"
            required
          />
        </div>

        <div className={`${styles.field} ${styles.fieldFull}`}>
          <label className={styles.label} htmlFor="material-name">
            Название
          </label>
          <input
            id="material-name"
            className={styles.input}
            value={canonicalName}
            onChange={(e) => setCanonicalName(e.target.value)}
            required
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="material-category">
            Категория
          </label>
          <input
            id="material-category"
            className={styles.input}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          />
        </div>

        <div className={`${styles.field} ${styles.fieldFull}`}>
          <label className={styles.label} htmlFor="material-attributes">
            Атрибуты (JSON)
          </label>
          <textarea
            id="material-attributes"
            className={styles.textarea}
            value={attributesText}
            onChange={(e) => setAttributesText(e.target.value)}
            rows={4}
          />
        </div>
      </div>

      {error && <div className={styles.fieldError}>{error}</div>}

      <div className={styles.formActions}>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={submitting}>
          Отмена
        </Button>
        <Button type="submit" variant="primary" disabled={submitting}>
          {initial ? 'Сохранить' : 'Добавить материал'}
        </Button>
      </div>
    </form>
  );
}
