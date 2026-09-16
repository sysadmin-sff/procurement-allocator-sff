import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Button } from '../../components/Button';
import type { Category, Material, MaterialCreate } from '../../api/types';
import { useCategories } from '../../hooks/useCategories';
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

function findCategoryIdByName(categories: Category[], name: string | undefined): string {
  if (!name) return '';
  return categories.find((c) => c.name === name)?.id ?? '';
}

export function MaterialForm({ initial, onCancel, onSubmit }: MaterialFormProps) {
  const { categories, loading: categoriesLoading } = useCategories();
  const [canonicalName, setCanonicalName] = useState(initial?.canonical_name ?? '');
  const [categoryId, setCategoryId] = useState('');
  const [unit, setUnit] = useState(initial?.unit ?? '');
  const [attributesText, setAttributesText] = useState(() => toAttributesText(initial));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!initial || categories.length === 0) return;
    setCategoryId((current) => current || findCategoryIdByName(categories, initial.category_name));
  }, [categories, initial]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (!canonicalName.trim() || !unit.trim() || !categoryId) {
      setError('Название, категория и единица измерения обязательны');
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
        canonical_name: canonicalName.trim(),
        category_id: categoryId,
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
          internal_sku ({initial.internal_sku}) — ключ идентичности материала (см. CLAUDE.md):
          выдан один раз при создании и больше не меняется, в том числе при смене категории.
        </div>
      )}

      <div className={styles.formGrid}>
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
          <select
            id="material-category"
            className={styles.select}
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
            disabled={categoriesLoading}
            required
          >
            <option value="" disabled>
              {categoriesLoading ? 'Загрузка…' : 'Выберите категорию'}
            </option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
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
