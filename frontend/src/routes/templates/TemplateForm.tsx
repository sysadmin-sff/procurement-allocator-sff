import { useState } from 'react';
import type { FormEvent } from 'react';
import { Button } from '../../components/Button';
import type { ProjectTemplateCreate } from '../../api/types';
import styles from '../../components/CrudScreen.module.css';

interface TemplateFormProps {
  initialName?: string;
  submitLabel: string;
  onCancel: () => void;
  onSubmit: (payload: ProjectTemplateCreate) => Promise<void>;
}

export function TemplateForm({ initialName, submitLabel, onCancel, onSubmit }: TemplateFormProps) {
  const [name, setName] = useState(initialName ?? '');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (!name.trim()) {
      setError('Название шаблона обязательно');
      return;
    }

    setSubmitting(true);
    try {
      await onSubmit({ name: name.trim() });
    } catch {
      // ApiError surfaces via the parent's error state; keep the form open to retry.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className={styles.cardPadded} onSubmit={handleSubmit}>
      <div className={styles.field}>
        <label className={styles.label} htmlFor="template-name">
          Название шаблона
        </label>
        <input
          id="template-name"
          className={styles.input}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Например: Стандартная дверь"
          required
        />
      </div>

      {error && <div className={styles.fieldError}>{error}</div>}

      <div className={styles.formActions}>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={submitting}>
          Отмена
        </Button>
        <Button type="submit" variant="primary" disabled={submitting}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
