import { useState } from 'react';
import type { FormEvent } from 'react';
import { Button } from '../../components/Button';
import type { UserCreate, UserRole } from '../../api/types';
import styles from '../../components/CrudScreen.module.css';

interface UserFormProps {
  onCancel: () => void;
  onSubmit: (payload: UserCreate) => Promise<void>;
}

export function UserForm({ onCancel, onSubmit }: UserFormProps) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<UserRole>('employee');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (!email.trim()) {
      setError('Email обязателен');
      return;
    }

    setSubmitting(true);
    try {
      await onSubmit({ email: email.trim(), role });
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
          <label className={styles.label} htmlFor="user-email">
            Email
          </label>
          <input
            id="user-email"
            type="email"
            className={styles.input}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="user-role">
            Роль
          </label>
          <select
            id="user-role"
            className={styles.select}
            value={role}
            onChange={(e) => setRole(e.target.value as UserRole)}
          >
            <option value="employee">Сотрудник</option>
            <option value="admin">Администратор</option>
          </select>
        </div>
      </div>

      {error && <div className={styles.fieldError}>{error}</div>}

      <div className={styles.formActions}>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={submitting}>
          Отмена
        </Button>
        <Button type="submit" variant="primary" disabled={submitting}>
          Добавить пользователя
        </Button>
      </div>
    </form>
  );
}
